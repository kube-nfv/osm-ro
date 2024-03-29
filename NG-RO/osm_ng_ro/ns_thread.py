# -*- coding: utf-8 -*-

##
# Copyright 2020 Telefonica Investigacion y Desarrollo, S.A.U.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
#
##

"""
This is thread that interacts with a VIM. It processes TASKs sequentially against a single VIM.
The tasks are stored at database in table ro_tasks
A single ro_task refers to a VIM element (flavor, image, network, ...).
A ro_task can contain several 'tasks', each one with a target, where to store the results
"""

from copy import deepcopy
from http import HTTPStatus
import logging
from os import makedirs
from os import path
import queue
import threading
import time
import traceback
from typing import Dict
from unittest.mock import Mock

from importlib_metadata import entry_points
from osm_common.dbbase import DbException
from osm_ng_ro.vim_admin import LockRenew
from osm_ro_plugin import sdnconn
from osm_ro_plugin import vimconn
from osm_ro_plugin.sdn_dummy import SdnDummyConnector
from osm_ro_plugin.vim_dummy import VimDummyConnector
import yaml

__author__ = "Alfonso Tierno"
__date__ = "$28-Sep-2017 12:07:15$"


def deep_get(target_dict, *args, **kwargs):
    """
    Get a value from target_dict entering in the nested keys. If keys does not exist, it returns None
    Example target_dict={a: {b: 5}}; key_list=[a,b] returns 5; both key_list=[a,b,c] and key_list=[f,h] return None
    :param target_dict: dictionary to be read
    :param args: list of keys to read from  target_dict
    :param kwargs: only can contain default=value to return if key is not present in the nested dictionary
    :return: The wanted value if exists, None or default otherwise
    """
    for key in args:
        if not isinstance(target_dict, dict) or key not in target_dict:
            return kwargs.get("default")
        target_dict = target_dict[key]
    return target_dict


class NsWorkerException(Exception):
    pass


class FailingConnector:
    def __init__(self, error_msg):
        self.error_msg = error_msg

        for method in dir(vimconn.VimConnector):
            if method[0] != "_":
                setattr(
                    self, method, Mock(side_effect=vimconn.VimConnException(error_msg))
                )

        for method in dir(sdnconn.SdnConnectorBase):
            if method[0] != "_":
                setattr(
                    self, method, Mock(side_effect=sdnconn.SdnConnectorError(error_msg))
                )


class NsWorkerExceptionNotFound(NsWorkerException):
    pass


class VimInteractionBase:
    """Base class to call VIM/SDN for creating, deleting and refresh networks, VMs, flavors, ...
    It implements methods that does nothing and return ok"""

    def __init__(self, db, my_vims, db_vims, logger):
        self.db = db
        self.logger = logger
        self.my_vims = my_vims
        self.db_vims = db_vims

    def new(self, ro_task, task_index, task_depends):
        return "BUILD", {}

    def refresh(self, ro_task):
        """skip calling VIM to get image, flavor status. Assumes ok"""
        if ro_task["vim_info"]["vim_status"] == "VIM_ERROR":
            return "FAILED", {}

        return "DONE", {}

    def delete(self, ro_task, task_index):
        """skip calling VIM to delete image. Assumes ok"""
        return "DONE", {}

    def exec(self, ro_task, task_index, task_depends):
        return "DONE", None, None


class VimInteractionNet(VimInteractionBase):
    def new(self, ro_task, task_index, task_depends):
        vim_net_id = None
        task = ro_task["tasks"][task_index]
        task_id = task["task_id"]
        created = False
        created_items = {}
        target_vim = self.my_vims[ro_task["target_id"]]
        mgmtnet = False
        mgmtnet_defined_in_vim = False

        try:
            # FIND
            if task.get("find_params"):
                # if management, get configuration of VIM
                if task["find_params"].get("filter_dict"):
                    vim_filter = task["find_params"]["filter_dict"]
                # management network
                elif task["find_params"].get("mgmt"):
                    mgmtnet = True
                    if deep_get(
                        self.db_vims[ro_task["target_id"]],
                        "config",
                        "management_network_id",
                    ):
                        mgmtnet_defined_in_vim = True
                        vim_filter = {
                            "id": self.db_vims[ro_task["target_id"]]["config"][
                                "management_network_id"
                            ]
                        }
                    elif deep_get(
                        self.db_vims[ro_task["target_id"]],
                        "config",
                        "management_network_name",
                    ):
                        mgmtnet_defined_in_vim = True
                        vim_filter = {
                            "name": self.db_vims[ro_task["target_id"]]["config"][
                                "management_network_name"
                            ]
                        }
                    else:
                        vim_filter = {"name": task["find_params"]["name"]}
                else:
                    raise NsWorkerExceptionNotFound(
                        "Invalid find_params for new_net {}".format(task["find_params"])
                    )

                vim_nets = target_vim.get_network_list(vim_filter)
                if not vim_nets and not task.get("params"):
                    # If there is mgmt-network in the descriptor,
                    # there is no mapping of that network to a VIM network in the descriptor,
                    # also there is no mapping in the "--config" parameter or at VIM creation;
                    # that mgmt-network will be created.
                    if mgmtnet and not mgmtnet_defined_in_vim:
                        net_name = (
                            vim_filter.get("name")
                            if vim_filter.get("name")
                            else vim_filter.get("id")[:16]
                        )
                        vim_net_id, created_items = target_vim.new_network(
                            net_name, None
                        )
                        self.logger.debug(
                            "Created mgmt network vim_net_id: {}".format(vim_net_id)
                        )
                        created = True
                    else:
                        raise NsWorkerExceptionNotFound(
                            "Network not found with this criteria: '{}'".format(
                                task.get("find_params")
                            )
                        )
                elif len(vim_nets) > 1:
                    raise NsWorkerException(
                        "More than one network found with this criteria: '{}'".format(
                            task["find_params"]
                        )
                    )

                if vim_nets:
                    vim_net_id = vim_nets[0]["id"]
            else:
                # CREATE
                params = task["params"]
                vim_net_id, created_items = target_vim.new_network(**params)
                created = True

            ro_vim_item_update = {
                "vim_id": vim_net_id,
                "vim_status": "BUILD",
                "created": created,
                "created_items": created_items,
                "vim_details": None,
                "vim_message": None,
            }
            self.logger.debug(
                "task={} {} new-net={} created={}".format(
                    task_id, ro_task["target_id"], vim_net_id, created
                )
            )

            return "BUILD", ro_vim_item_update
        except (vimconn.VimConnException, NsWorkerException) as e:
            self.logger.error(
                "task={} vim={} new-net: {}".format(task_id, ro_task["target_id"], e)
            )
            ro_vim_item_update = {
                "vim_status": "VIM_ERROR",
                "created": created,
                "vim_message": str(e),
            }

            return "FAILED", ro_vim_item_update

    def refresh(self, ro_task):
        """Call VIM to get network status"""
        ro_task_id = ro_task["_id"]
        target_vim = self.my_vims[ro_task["target_id"]]
        vim_id = ro_task["vim_info"]["vim_id"]
        net_to_refresh_list = [vim_id]

        try:
            vim_dict = target_vim.refresh_nets_status(net_to_refresh_list)
            vim_info = vim_dict[vim_id]

            if vim_info["status"] == "ACTIVE":
                task_status = "DONE"
            elif vim_info["status"] == "BUILD":
                task_status = "BUILD"
            else:
                task_status = "FAILED"
        except vimconn.VimConnException as e:
            # Mark all tasks at VIM_ERROR status
            self.logger.error(
                "ro_task={} vim={} get-net={}: {}".format(
                    ro_task_id, ro_task["target_id"], vim_id, e
                )
            )
            vim_info = {"status": "VIM_ERROR", "error_msg": str(e)}
            task_status = "FAILED"

        ro_vim_item_update = {}
        if ro_task["vim_info"]["vim_status"] != vim_info["status"]:
            ro_vim_item_update["vim_status"] = vim_info["status"]

        if ro_task["vim_info"]["vim_name"] != vim_info.get("name"):
            ro_vim_item_update["vim_name"] = vim_info.get("name")

        if vim_info["status"] in ("ERROR", "VIM_ERROR"):
            if ro_task["vim_info"]["vim_message"] != vim_info.get("error_msg"):
                ro_vim_item_update["vim_message"] = vim_info.get("error_msg")
        elif vim_info["status"] == "DELETED":
            ro_vim_item_update["vim_id"] = None
            ro_vim_item_update["vim_message"] = "Deleted externally"
        else:
            if ro_task["vim_info"]["vim_details"] != vim_info["vim_info"]:
                ro_vim_item_update["vim_details"] = vim_info["vim_info"]

        if ro_vim_item_update:
            self.logger.debug(
                "ro_task={} {} get-net={}: status={} {}".format(
                    ro_task_id,
                    ro_task["target_id"],
                    vim_id,
                    ro_vim_item_update.get("vim_status"),
                    (
                        ro_vim_item_update.get("vim_message")
                        if ro_vim_item_update.get("vim_status") != "ACTIVE"
                        else ""
                    ),
                )
            )

        return task_status, ro_vim_item_update

    def delete(self, ro_task, task_index):
        task = ro_task["tasks"][task_index]
        task_id = task["task_id"]
        net_vim_id = ro_task["vim_info"]["vim_id"]
        ro_vim_item_update_ok = {
            "vim_status": "DELETED",
            "created": False,
            "vim_message": "DELETED",
            "vim_id": None,
        }

        try:
            if net_vim_id or ro_task["vim_info"]["created_items"]:
                target_vim = self.my_vims[ro_task["target_id"]]
                target_vim.delete_network(
                    net_vim_id, ro_task["vim_info"]["created_items"]
                )
        except vimconn.VimConnNotFoundException:
            ro_vim_item_update_ok["vim_message"] = "already deleted"
        except vimconn.VimConnException as e:
            self.logger.error(
                "ro_task={} vim={} del-net={}: {}".format(
                    ro_task["_id"], ro_task["target_id"], net_vim_id, e
                )
            )
            ro_vim_item_update = {
                "vim_status": "VIM_ERROR",
                "vim_message": "Error while deleting: {}".format(e),
            }

            return "FAILED", ro_vim_item_update

        self.logger.debug(
            "task={} {} del-net={} {}".format(
                task_id,
                ro_task["target_id"],
                net_vim_id,
                ro_vim_item_update_ok.get("vim_message", ""),
            )
        )

        return "DONE", ro_vim_item_update_ok


class VimInteractionClassification(VimInteractionBase):
    def new(self, ro_task, task_index, task_depends):
        task = ro_task["tasks"][task_index]
        task_id = task["task_id"]
        created = False
        target_vim = self.my_vims[ro_task["target_id"]]

        try:
            created = True
            params = task["params"]
            params_copy = deepcopy(params)

            name = params_copy.pop("name")
            logical_source_port_index = int(
                params_copy.pop("logical_source_port_index")
            )
            logical_source_port = params_copy["logical_source_port"]

            if logical_source_port.startswith("TASK-"):
                vm_id = task_depends[logical_source_port]
                params_copy["logical_source_port"] = target_vim.refresh_vms_status(
                    [vm_id]
                )[vm_id]["interfaces"][logical_source_port_index]["vim_interface_id"]

            vim_classification_id = target_vim.new_classification(
                name, "legacy_flow_classifier", params_copy
            )

            ro_vim_item_update = {
                "vim_id": vim_classification_id,
                "vim_status": "DONE",
                "created": created,
                "vim_details": None,
                "vim_message": None,
            }
            self.logger.debug(
                "task={} {} created={}".format(task_id, ro_task["target_id"], created)
            )

            return "DONE", ro_vim_item_update
        except (vimconn.VimConnException, NsWorkerException) as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(
                "task={} {} new-vm: {}".format(task_id, ro_task["target_id"], e)
            )
            ro_vim_item_update = {
                "vim_status": "VIM_ERROR",
                "created": created,
                "vim_message": str(e),
            }

            return "FAILED", ro_vim_item_update

    def delete(self, ro_task, task_index):
        task = ro_task["tasks"][task_index]
        task_id = task["task_id"]
        classification_vim_id = ro_task["vim_info"]["vim_id"]
        ro_vim_item_update_ok = {
            "vim_status": "DELETED",
            "created": False,
            "vim_message": "DELETED",
            "vim_id": None,
        }

        try:
            if classification_vim_id:
                target_vim = self.my_vims[ro_task["target_id"]]
                target_vim.delete_classification(classification_vim_id)
        except vimconn.VimConnNotFoundException:
            ro_vim_item_update_ok["vim_message"] = "already deleted"
        except vimconn.VimConnException as e:
            self.logger.error(
                "ro_task={} vim={} del-classification={}: {}".format(
                    ro_task["_id"], ro_task["target_id"], classification_vim_id, e
                )
            )
            ro_vim_item_update = {
                "vim_status": "VIM_ERROR",
                "vim_message": "Error while deleting: {}".format(e),
            }

            return "FAILED", ro_vim_item_update

        self.logger.debug(
            "task={} {} del-classification={} {}".format(
                task_id,
                ro_task["target_id"],
                classification_vim_id,
                ro_vim_item_update_ok.get("vim_message", ""),
            )
        )

        return "DONE", ro_vim_item_update_ok


class VimInteractionSfi(VimInteractionBase):
    def new(self, ro_task, task_index, task_depends):
        task = ro_task["tasks"][task_index]
        task_id = task["task_id"]
        created = False
        target_vim = self.my_vims[ro_task["target_id"]]

        try:
            created = True
            params = task["params"]
            params_copy = deepcopy(params)
            name = params_copy["name"]
            ingress_port = params_copy["ingress_port"]
            egress_port = params_copy["egress_port"]
            ingress_port_index = params_copy["ingress_port_index"]
            egress_port_index = params_copy["egress_port_index"]

            ingress_port_id = ingress_port
            egress_port_id = egress_port

            vm_id = task_depends[ingress_port]

            if ingress_port.startswith("TASK-"):
                ingress_port_id = target_vim.refresh_vms_status([vm_id])[vm_id][
                    "interfaces"
                ][ingress_port_index]["vim_interface_id"]

            if ingress_port == egress_port:
                egress_port_id = ingress_port_id
            else:
                if egress_port.startswith("TASK-"):
                    egress_port_id = target_vim.refresh_vms_status([vm_id])[vm_id][
                        "interfaces"
                    ][egress_port_index]["vim_interface_id"]

            ingress_port_id_list = [ingress_port_id]
            egress_port_id_list = [egress_port_id]

            vim_sfi_id = target_vim.new_sfi(
                name, ingress_port_id_list, egress_port_id_list, sfc_encap=False
            )

            ro_vim_item_update = {
                "vim_id": vim_sfi_id,
                "vim_status": "DONE",
                "created": created,
                "vim_details": None,
                "vim_message": None,
            }
            self.logger.debug(
                "task={} {} created={}".format(task_id, ro_task["target_id"], created)
            )

            return "DONE", ro_vim_item_update
        except (vimconn.VimConnException, NsWorkerException) as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(
                "task={} {} new-vm: {}".format(task_id, ro_task["target_id"], e)
            )
            ro_vim_item_update = {
                "vim_status": "VIM_ERROR",
                "created": created,
                "vim_message": str(e),
            }

            return "FAILED", ro_vim_item_update

    def delete(self, ro_task, task_index):
        task = ro_task["tasks"][task_index]
        task_id = task["task_id"]
        sfi_vim_id = ro_task["vim_info"]["vim_id"]
        ro_vim_item_update_ok = {
            "vim_status": "DELETED",
            "created": False,
            "vim_message": "DELETED",
            "vim_id": None,
        }

        try:
            if sfi_vim_id:
                target_vim = self.my_vims[ro_task["target_id"]]
                target_vim.delete_sfi(sfi_vim_id)
        except vimconn.VimConnNotFoundException:
            ro_vim_item_update_ok["vim_message"] = "already deleted"
        except vimconn.VimConnException as e:
            self.logger.error(
                "ro_task={} vim={} del-sfi={}: {}".format(
                    ro_task["_id"], ro_task["target_id"], sfi_vim_id, e
                )
            )
            ro_vim_item_update = {
                "vim_status": "VIM_ERROR",
                "vim_message": "Error while deleting: {}".format(e),
            }

            return "FAILED", ro_vim_item_update

        self.logger.debug(
            "task={} {} del-sfi={} {}".format(
                task_id,
                ro_task["target_id"],
                sfi_vim_id,
                ro_vim_item_update_ok.get("vim_message", ""),
            )
        )

        return "DONE", ro_vim_item_update_ok


class VimInteractionSf(VimInteractionBase):
    def new(self, ro_task, task_index, task_depends):
        task = ro_task["tasks"][task_index]
        task_id = task["task_id"]
        created = False
        target_vim = self.my_vims[ro_task["target_id"]]

        try:
            created = True
            params = task["params"]
            params_copy = deepcopy(params)
            name = params_copy["name"]
            sfi_list = params_copy["sfis"]
            sfi_id_list = []

            for sfi in sfi_list:
                sfi_id = task_depends[sfi] if sfi.startswith("TASK-") else sfi
                sfi_id_list.append(sfi_id)

            vim_sf_id = target_vim.new_sf(name, sfi_id_list, sfc_encap=False)

            ro_vim_item_update = {
                "vim_id": vim_sf_id,
                "vim_status": "DONE",
                "created": created,
                "vim_details": None,
                "vim_message": None,
            }
            self.logger.debug(
                "task={} {} created={}".format(task_id, ro_task["target_id"], created)
            )

            return "DONE", ro_vim_item_update
        except (vimconn.VimConnException, NsWorkerException) as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(
                "task={} {} new-vm: {}".format(task_id, ro_task["target_id"], e)
            )
            ro_vim_item_update = {
                "vim_status": "VIM_ERROR",
                "created": created,
                "vim_message": str(e),
            }

            return "FAILED", ro_vim_item_update

    def delete(self, ro_task, task_index):
        task = ro_task["tasks"][task_index]
        task_id = task["task_id"]
        sf_vim_id = ro_task["vim_info"]["vim_id"]
        ro_vim_item_update_ok = {
            "vim_status": "DELETED",
            "created": False,
            "vim_message": "DELETED",
            "vim_id": None,
        }

        try:
            if sf_vim_id:
                target_vim = self.my_vims[ro_task["target_id"]]
                target_vim.delete_sf(sf_vim_id)
        except vimconn.VimConnNotFoundException:
            ro_vim_item_update_ok["vim_message"] = "already deleted"
        except vimconn.VimConnException as e:
            self.logger.error(
                "ro_task={} vim={} del-sf={}: {}".format(
                    ro_task["_id"], ro_task["target_id"], sf_vim_id, e
                )
            )
            ro_vim_item_update = {
                "vim_status": "VIM_ERROR",
                "vim_message": "Error while deleting: {}".format(e),
            }

            return "FAILED", ro_vim_item_update

        self.logger.debug(
            "task={} {} del-sf={} {}".format(
                task_id,
                ro_task["target_id"],
                sf_vim_id,
                ro_vim_item_update_ok.get("vim_message", ""),
            )
        )

        return "DONE", ro_vim_item_update_ok


class VimInteractionSfp(VimInteractionBase):
    def new(self, ro_task, task_index, task_depends):
        task = ro_task["tasks"][task_index]
        task_id = task["task_id"]
        created = False
        target_vim = self.my_vims[ro_task["target_id"]]

        try:
            created = True
            params = task["params"]
            params_copy = deepcopy(params)
            name = params_copy["name"]
            sf_list = params_copy["sfs"]
            classification_list = params_copy["classifications"]

            classification_id_list = []
            sf_id_list = []

            for classification in classification_list:
                classi_id = (
                    task_depends[classification]
                    if classification.startswith("TASK-")
                    else classification
                )
                classification_id_list.append(classi_id)

            for sf in sf_list:
                sf_id = task_depends[sf] if sf.startswith("TASK-") else sf
                sf_id_list.append(sf_id)

            vim_sfp_id = target_vim.new_sfp(
                name, classification_id_list, sf_id_list, sfc_encap=False
            )

            ro_vim_item_update = {
                "vim_id": vim_sfp_id,
                "vim_status": "DONE",
                "created": created,
                "vim_details": None,
                "vim_message": None,
            }
            self.logger.debug(
                "task={} {} created={}".format(task_id, ro_task["target_id"], created)
            )

            return "DONE", ro_vim_item_update
        except (vimconn.VimConnException, NsWorkerException) as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(
                "task={} {} new-vm: {}".format(task_id, ro_task["target_id"], e)
            )
            ro_vim_item_update = {
                "vim_status": "VIM_ERROR",
                "created": created,
                "vim_message": str(e),
            }

            return "FAILED", ro_vim_item_update

    def delete(self, ro_task, task_index):
        task = ro_task["tasks"][task_index]
        task_id = task["task_id"]
        sfp_vim_id = ro_task["vim_info"]["vim_id"]
        ro_vim_item_update_ok = {
            "vim_status": "DELETED",
            "created": False,
            "vim_message": "DELETED",
            "vim_id": None,
        }

        try:
            if sfp_vim_id:
                target_vim = self.my_vims[ro_task["target_id"]]
                target_vim.delete_sfp(sfp_vim_id)
        except vimconn.VimConnNotFoundException:
            ro_vim_item_update_ok["vim_message"] = "already deleted"
        except vimconn.VimConnException as e:
            self.logger.error(
                "ro_task={} vim={} del-sfp={}: {}".format(
                    ro_task["_id"], ro_task["target_id"], sfp_vim_id, e
                )
            )
            ro_vim_item_update = {
                "vim_status": "VIM_ERROR",
                "vim_message": "Error while deleting: {}".format(e),
            }

            return "FAILED", ro_vim_item_update

        self.logger.debug(
            "task={} {} del-sfp={} {}".format(
                task_id,
                ro_task["target_id"],
                sfp_vim_id,
                ro_vim_item_update_ok.get("vim_message", ""),
            )
        )

        return "DONE", ro_vim_item_update_ok


class VimInteractionVdu(VimInteractionBase):
    max_retries_inject_ssh_key = 20  # 20 times
    time_retries_inject_ssh_key = 30  # wevery 30 seconds

    def new(self, ro_task, task_index, task_depends):
        task = ro_task["tasks"][task_index]
        task_id = task["task_id"]
        created = False
        target_vim = self.my_vims[ro_task["target_id"]]
        try:
            created = True
            params = task["params"]
            params_copy = deepcopy(params)
            net_list = params_copy["net_list"]

            for net in net_list:
                # change task_id into network_id
                if "net_id" in net and net["net_id"].startswith("TASK-"):
                    network_id = task_depends[net["net_id"]]

                    if not network_id:
                        raise NsWorkerException(
                            "Cannot create VM because depends on a network not created or found "
                            "for {}".format(net["net_id"])
                        )

                    net["net_id"] = network_id

            if params_copy["image_id"].startswith("TASK-"):
                params_copy["image_id"] = task_depends[params_copy["image_id"]]

            if params_copy["flavor_id"].startswith("TASK-"):
                params_copy["flavor_id"] = task_depends[params_copy["flavor_id"]]

            affinity_group_list = params_copy["affinity_group_list"]
            for affinity_group in affinity_group_list:
                # change task_id into affinity_group_id
                if "affinity_group_id" in affinity_group and affinity_group[
                    "affinity_group_id"
                ].startswith("TASK-"):
                    affinity_group_id = task_depends[
                        affinity_group["affinity_group_id"]
                    ]

                    if not affinity_group_id:
                        raise NsWorkerException(
                            "found for {}".format(affinity_group["affinity_group_id"])
                        )

                    affinity_group["affinity_group_id"] = affinity_group_id
            vim_vm_id, created_items = target_vim.new_vminstance(**params_copy)
            interfaces = [iface["vim_id"] for iface in params_copy["net_list"]]

            # add to created items previous_created_volumes (healing)
            if task.get("previous_created_volumes"):
                for k, v in task["previous_created_volumes"].items():
                    created_items[k] = v

            ro_vim_item_update = {
                "vim_id": vim_vm_id,
                "vim_status": "BUILD",
                "created": created,
                "created_items": created_items,
                "vim_details": None,
                "vim_message": None,
                "interfaces_vim_ids": interfaces,
                "interfaces": [],
                "interfaces_backup": [],
            }
            self.logger.debug(
                "task={} {} new-vm={} created={}".format(
                    task_id, ro_task["target_id"], vim_vm_id, created
                )
            )

            return "BUILD", ro_vim_item_update
        except (vimconn.VimConnException, NsWorkerException) as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(
                "task={} {} new-vm: {}".format(task_id, ro_task["target_id"], e)
            )
            ro_vim_item_update = {
                "vim_status": "VIM_ERROR",
                "created": created,
                "vim_message": str(e),
            }

            return "FAILED", ro_vim_item_update

    def delete(self, ro_task, task_index):
        task = ro_task["tasks"][task_index]
        task_id = task["task_id"]
        vm_vim_id = ro_task["vim_info"]["vim_id"]
        ro_vim_item_update_ok = {
            "vim_status": "DELETED",
            "created": False,
            "vim_message": "DELETED",
            "vim_id": None,
        }

        try:
            self.logger.debug(
                "delete_vminstance: vm_vim_id={} created_items={}".format(
                    vm_vim_id, ro_task["vim_info"]["created_items"]
                )
            )
            if vm_vim_id or ro_task["vim_info"]["created_items"]:
                target_vim = self.my_vims[ro_task["target_id"]]
                target_vim.delete_vminstance(
                    vm_vim_id,
                    ro_task["vim_info"]["created_items"],
                    ro_task["vim_info"].get("volumes_to_hold", []),
                )
        except vimconn.VimConnNotFoundException:
            ro_vim_item_update_ok["vim_message"] = "already deleted"
        except vimconn.VimConnException as e:
            self.logger.error(
                "ro_task={} vim={} del-vm={}: {}".format(
                    ro_task["_id"], ro_task["target_id"], vm_vim_id, e
                )
            )
            ro_vim_item_update = {
                "vim_status": "VIM_ERROR",
                "vim_message": "Error while deleting: {}".format(e),
            }

            return "FAILED", ro_vim_item_update

        self.logger.debug(
            "task={} {} del-vm={} {}".format(
                task_id,
                ro_task["target_id"],
                vm_vim_id,
                ro_vim_item_update_ok.get("vim_message", ""),
            )
        )

        return "DONE", ro_vim_item_update_ok

    def refresh(self, ro_task):
        """Call VIM to get vm status"""
        ro_task_id = ro_task["_id"]
        target_vim = self.my_vims[ro_task["target_id"]]
        vim_id = ro_task["vim_info"]["vim_id"]

        if not vim_id:
            return None, None

        vm_to_refresh_list = [vim_id]
        try:
            vim_dict = target_vim.refresh_vms_status(vm_to_refresh_list)
            vim_info = vim_dict[vim_id]

            if vim_info["status"] == "ACTIVE":
                task_status = "DONE"
            elif vim_info["status"] == "BUILD":
                task_status = "BUILD"
            else:
                task_status = "FAILED"

            # try to load and parse vim_information
            try:
                vim_info_info = yaml.safe_load(vim_info["vim_info"])
                if vim_info_info.get("name"):
                    vim_info["name"] = vim_info_info["name"]
            except Exception as vim_info_error:
                self.logger.exception(
                    f"{vim_info_error} occured while getting the vim_info from yaml"
                )
        except vimconn.VimConnException as e:
            # Mark all tasks at VIM_ERROR status
            self.logger.error(
                "ro_task={} vim={} get-vm={}: {}".format(
                    ro_task_id, ro_task["target_id"], vim_id, e
                )
            )
            vim_info = {"status": "VIM_ERROR", "error_msg": str(e)}
            task_status = "FAILED"

        ro_vim_item_update = {}

        # Interfaces cannot be present if e.g. VM is not present, that is status=DELETED
        vim_interfaces = []
        if vim_info.get("interfaces"):
            for vim_iface_id in ro_task["vim_info"]["interfaces_vim_ids"]:
                iface = next(
                    (
                        iface
                        for iface in vim_info["interfaces"]
                        if vim_iface_id == iface["vim_interface_id"]
                    ),
                    None,
                )
                # if iface:
                #     iface.pop("vim_info", None)
                vim_interfaces.append(iface)

        task_create = next(
            t
            for t in ro_task["tasks"]
            if t and t["action"] == "CREATE" and t["status"] != "FINISHED"
        )
        if vim_interfaces and task_create.get("mgmt_vnf_interface") is not None:
            vim_interfaces[task_create["mgmt_vnf_interface"]][
                "mgmt_vnf_interface"
            ] = True

        mgmt_vdu_iface = task_create.get(
            "mgmt_vdu_interface", task_create.get("mgmt_vnf_interface", 0)
        )
        if vim_interfaces:
            vim_interfaces[mgmt_vdu_iface]["mgmt_vdu_interface"] = True

        if ro_task["vim_info"]["interfaces"] != vim_interfaces:
            ro_vim_item_update["interfaces"] = vim_interfaces

        if ro_task["vim_info"]["vim_status"] != vim_info["status"]:
            ro_vim_item_update["vim_status"] = vim_info["status"]

        if ro_task["vim_info"]["vim_name"] != vim_info.get("name"):
            ro_vim_item_update["vim_name"] = vim_info.get("name")

        if vim_info["status"] in ("ERROR", "VIM_ERROR"):
            if ro_task["vim_info"]["vim_message"] != vim_info.get("error_msg"):
                ro_vim_item_update["vim_message"] = vim_info.get("error_msg")
        elif vim_info["status"] == "DELETED":
            ro_vim_item_update["vim_id"] = None
            ro_vim_item_update["vim_message"] = "Deleted externally"
        else:
            if ro_task["vim_info"]["vim_details"] != vim_info["vim_info"]:
                ro_vim_item_update["vim_details"] = vim_info["vim_info"]

        if ro_vim_item_update:
            self.logger.debug(
                "ro_task={} {} get-vm={}: status={} {}".format(
                    ro_task_id,
                    ro_task["target_id"],
                    vim_id,
                    ro_vim_item_update.get("vim_status"),
                    (
                        ro_vim_item_update.get("vim_message")
                        if ro_vim_item_update.get("vim_status") != "ACTIVE"
                        else ""
                    ),
                )
            )

        return task_status, ro_vim_item_update

    def exec(self, ro_task, task_index, task_depends):
        task = ro_task["tasks"][task_index]
        task_id = task["task_id"]
        target_vim = self.my_vims[ro_task["target_id"]]
        db_task_update = {"retries": 0}
        retries = task.get("retries", 0)

        try:
            params = task["params"]
            params_copy = deepcopy(params)
            params_copy["ro_key"] = self.db.decrypt(
                params_copy.pop("private_key"),
                params_copy.pop("schema_version"),
                params_copy.pop("salt"),
            )
            params_copy["ip_addr"] = params_copy.pop("ip_address")
            target_vim.inject_user_key(**params_copy)
            self.logger.debug(
                "task={} {} action-vm=inject_key".format(task_id, ro_task["target_id"])
            )

            return (
                "DONE",
                None,
                db_task_update,
            )  # params_copy["key"]
        except (vimconn.VimConnException, NsWorkerException) as e:
            retries += 1

            self.logger.debug(traceback.format_exc())
            if retries < self.max_retries_inject_ssh_key:
                return (
                    "BUILD",
                    None,
                    {
                        "retries": retries,
                        "next_retry": self.time_retries_inject_ssh_key,
                    },
                )

            self.logger.error(
                "task={} {} inject-ssh-key: {}".format(task_id, ro_task["target_id"], e)
            )
            ro_vim_item_update = {"vim_message": str(e)}

            return "FAILED", ro_vim_item_update, db_task_update


class VimInteractionImage(VimInteractionBase):
    def new(self, ro_task, task_index, task_depends):
        task = ro_task["tasks"][task_index]
        task_id = task["task_id"]
        created = False
        created_items = {}
        target_vim = self.my_vims[ro_task["target_id"]]

        try:
            # FIND
            vim_image_id = ""
            if task.get("find_params"):
                vim_images = target_vim.get_image_list(
                    task["find_params"].get("filter_dict", {})
                )

                if not vim_images:
                    raise NsWorkerExceptionNotFound(
                        "Image not found with this criteria: '{}'".format(
                            task["find_params"]
                        )
                    )
                elif len(vim_images) > 1:
                    raise NsWorkerException(
                        "More than one image found with this criteria: '{}'".format(
                            task["find_params"]
                        )
                    )
                else:
                    vim_image_id = vim_images[0]["id"]

            ro_vim_item_update = {
                "vim_id": vim_image_id,
                "vim_status": "ACTIVE",
                "created": created,
                "created_items": created_items,
                "vim_details": None,
                "vim_message": None,
            }
            self.logger.debug(
                "task={} {} new-image={} created={}".format(
                    task_id, ro_task["target_id"], vim_image_id, created
                )
            )

            return "DONE", ro_vim_item_update
        except (NsWorkerException, vimconn.VimConnException) as e:
            self.logger.error(
                "task={} {} new-image: {}".format(task_id, ro_task["target_id"], e)
            )
            ro_vim_item_update = {
                "vim_status": "VIM_ERROR",
                "created": created,
                "vim_message": str(e),
            }

            return "FAILED", ro_vim_item_update


class VimInteractionSharedVolume(VimInteractionBase):
    def delete(self, ro_task, task_index):
        task = ro_task["tasks"][task_index]
        task_id = task["task_id"]
        shared_volume_vim_id = ro_task["vim_info"]["vim_id"]
        created_items = ro_task["vim_info"]["created_items"]
        ro_vim_item_update_ok = {
            "vim_status": "DELETED",
            "created": False,
            "vim_message": "DELETED",
            "vim_id": None,
        }
        if created_items and created_items.get(shared_volume_vim_id).get("keep"):
            ro_vim_item_update_ok = {
                "vim_status": "ACTIVE",
                "created": False,
                "vim_message": None,
            }
            return "DONE", ro_vim_item_update_ok
        try:
            if shared_volume_vim_id:
                target_vim = self.my_vims[ro_task["target_id"]]
                target_vim.delete_shared_volumes(shared_volume_vim_id)
        except vimconn.VimConnNotFoundException:
            ro_vim_item_update_ok["vim_message"] = "already deleted"
        except vimconn.VimConnException as e:
            self.logger.error(
                "ro_task={} vim={} del-shared-volume={}: {}".format(
                    ro_task["_id"], ro_task["target_id"], shared_volume_vim_id, e
                )
            )
            ro_vim_item_update = {
                "vim_status": "VIM_ERROR",
                "vim_message": "Error while deleting: {}".format(e),
            }

            return "FAILED", ro_vim_item_update

        self.logger.debug(
            "task={} {} del-shared-volume={} {}".format(
                task_id,
                ro_task["target_id"],
                shared_volume_vim_id,
                ro_vim_item_update_ok.get("vim_message", ""),
            )
        )

        return "DONE", ro_vim_item_update_ok

    def new(self, ro_task, task_index, task_depends):
        task = ro_task["tasks"][task_index]
        task_id = task["task_id"]
        created = False
        created_items = {}
        target_vim = self.my_vims[ro_task["target_id"]]

        try:
            shared_volume_vim_id = None
            shared_volume_data = None

            if task.get("params"):
                shared_volume_data = task["params"]

            if shared_volume_data:
                self.logger.info(
                    f"Creating the new shared_volume for {shared_volume_data}\n"
                )
                (
                    shared_volume_name,
                    shared_volume_vim_id,
                ) = target_vim.new_shared_volumes(shared_volume_data)
                created = True
                created_items[shared_volume_vim_id] = {
                    "name": shared_volume_name,
                    "keep": shared_volume_data.get("keep"),
                }

            ro_vim_item_update = {
                "vim_id": shared_volume_vim_id,
                "vim_status": "ACTIVE",
                "created": created,
                "created_items": created_items,
                "vim_details": None,
                "vim_message": None,
            }
            self.logger.debug(
                "task={} {} new-shared-volume={} created={}".format(
                    task_id, ro_task["target_id"], shared_volume_vim_id, created
                )
            )

            return "DONE", ro_vim_item_update
        except (vimconn.VimConnException, NsWorkerException) as e:
            self.logger.error(
                "task={} vim={} new-shared-volume:"
                " {}".format(task_id, ro_task["target_id"], e)
            )
            ro_vim_item_update = {
                "vim_status": "VIM_ERROR",
                "created": created,
                "vim_message": str(e),
            }

            return "FAILED", ro_vim_item_update


class VimInteractionFlavor(VimInteractionBase):
    def delete(self, ro_task, task_index):
        task = ro_task["tasks"][task_index]
        task_id = task["task_id"]
        flavor_vim_id = ro_task["vim_info"]["vim_id"]
        ro_vim_item_update_ok = {
            "vim_status": "DELETED",
            "created": False,
            "vim_message": "DELETED",
            "vim_id": None,
        }

        try:
            if flavor_vim_id:
                target_vim = self.my_vims[ro_task["target_id"]]
                target_vim.delete_flavor(flavor_vim_id)
        except vimconn.VimConnNotFoundException:
            ro_vim_item_update_ok["vim_message"] = "already deleted"
        except vimconn.VimConnException as e:
            self.logger.error(
                "ro_task={} vim={} del-flavor={}: {}".format(
                    ro_task["_id"], ro_task["target_id"], flavor_vim_id, e
                )
            )
            ro_vim_item_update = {
                "vim_status": "VIM_ERROR",
                "vim_message": "Error while deleting: {}".format(e),
            }

            return "FAILED", ro_vim_item_update

        self.logger.debug(
            "task={} {} del-flavor={} {}".format(
                task_id,
                ro_task["target_id"],
                flavor_vim_id,
                ro_vim_item_update_ok.get("vim_message", ""),
            )
        )

        return "DONE", ro_vim_item_update_ok

    def new(self, ro_task, task_index, task_depends):
        task = ro_task["tasks"][task_index]
        task_id = task["task_id"]
        created = False
        created_items = {}
        target_vim = self.my_vims[ro_task["target_id"]]
        try:
            # FIND
            vim_flavor_id = None

            if task.get("find_params", {}).get("vim_flavor_id"):
                vim_flavor_id = task["find_params"]["vim_flavor_id"]
                db_nsr = self.db.get_one("nsrs", {"_id": task["nsr_id"]})
                for vnfr_id in db_nsr.get("constituent-vnfr-ref"):
                    db_vnfr = self.db.get_one("vnfrs", {"_id": vnfr_id})
                    for each_flavor in db_nsr["flavor"]:
                        nsd_flavor_id = each_flavor["id"]
                        for vdur in db_vnfr["vdur"]:
                            if (
                                vdur.get("ns-flavor-id")
                                and vdur.get("ns-flavor-id") == nsd_flavor_id
                            ):
                                if vdur["additionalParams"]["OSM"].get("vim_flavor_id"):
                                    flavor_id = vdur["additionalParams"]["OSM"][
                                        "vim_flavor_id"
                                    ]
                                    flavor_details = target_vim.get_flavor(flavor_id)
                                    flavor_dict = {
                                        "memory-mb": flavor_details["ram"],
                                        "storage-gb": flavor_details["disk"],
                                        "vcpu-count": flavor_details["vcpus"],
                                    }
                                    each_flavor.update(flavor_dict)
                self.db.set_one("nsrs", {"_id": task["nsr_id"]}, db_nsr)
            elif task.get("find_params", {}).get("flavor_data"):
                try:
                    flavor_data = task["find_params"]["flavor_data"]
                    vim_flavor_id = target_vim.get_flavor_id_from_data(flavor_data)
                except vimconn.VimConnNotFoundException as flavor_not_found_msg:
                    self.logger.warning(
                        f"VimConnNotFoundException occured: {flavor_not_found_msg}"
                    )

            if not vim_flavor_id and task.get("params"):
                # CREATE
                flavor_data = task["params"]["flavor_data"]
                vim_flavor_id = target_vim.new_flavor(flavor_data)
                created = True

            ro_vim_item_update = {
                "vim_id": vim_flavor_id,
                "vim_status": "ACTIVE",
                "created": created,
                "created_items": created_items,
                "vim_details": None,
                "vim_message": None,
            }
            self.logger.debug(
                "task={} {} new-flavor={} created={}".format(
                    task_id, ro_task["target_id"], vim_flavor_id, created
                )
            )

            return "DONE", ro_vim_item_update
        except (vimconn.VimConnException, NsWorkerException) as e:
            self.logger.error(
                "task={} vim={} new-flavor: {}".format(task_id, ro_task["target_id"], e)
            )
            ro_vim_item_update = {
                "vim_status": "VIM_ERROR",
                "created": created,
                "vim_message": str(e),
            }

            return "FAILED", ro_vim_item_update


class VimInteractionAffinityGroup(VimInteractionBase):
    def delete(self, ro_task, task_index):
        task = ro_task["tasks"][task_index]
        task_id = task["task_id"]
        affinity_group_vim_id = ro_task["vim_info"]["vim_id"]
        ro_vim_item_update_ok = {
            "vim_status": "DELETED",
            "created": False,
            "vim_message": "DELETED",
            "vim_id": None,
        }

        try:
            if affinity_group_vim_id:
                target_vim = self.my_vims[ro_task["target_id"]]
                target_vim.delete_affinity_group(affinity_group_vim_id)
        except vimconn.VimConnNotFoundException:
            ro_vim_item_update_ok["vim_message"] = "already deleted"
        except vimconn.VimConnException as e:
            self.logger.error(
                "ro_task={} vim={} del-affinity-or-anti-affinity-group={}: {}".format(
                    ro_task["_id"], ro_task["target_id"], affinity_group_vim_id, e
                )
            )
            ro_vim_item_update = {
                "vim_status": "VIM_ERROR",
                "vim_message": "Error while deleting: {}".format(e),
            }

            return "FAILED", ro_vim_item_update

        self.logger.debug(
            "task={} {} del-affinity-or-anti-affinity-group={} {}".format(
                task_id,
                ro_task["target_id"],
                affinity_group_vim_id,
                ro_vim_item_update_ok.get("vim_message", ""),
            )
        )

        return "DONE", ro_vim_item_update_ok

    def new(self, ro_task, task_index, task_depends):
        task = ro_task["tasks"][task_index]
        task_id = task["task_id"]
        created = False
        created_items = {}
        target_vim = self.my_vims[ro_task["target_id"]]

        try:
            affinity_group_vim_id = None
            affinity_group_data = None
            param_affinity_group_id = ""

            if task.get("params"):
                affinity_group_data = task["params"].get("affinity_group_data")

            if affinity_group_data and affinity_group_data.get("vim-affinity-group-id"):
                try:
                    param_affinity_group_id = task["params"]["affinity_group_data"].get(
                        "vim-affinity-group-id"
                    )
                    affinity_group_vim_id = target_vim.get_affinity_group(
                        param_affinity_group_id
                    ).get("id")
                except vimconn.VimConnNotFoundException:
                    self.logger.error(
                        "task={} {} new-affinity-or-anti-affinity-group. Provided VIM Affinity Group ID {}"
                        "could not be found at VIM. Creating a new one.".format(
                            task_id, ro_task["target_id"], param_affinity_group_id
                        )
                    )

            if not affinity_group_vim_id and affinity_group_data:
                affinity_group_vim_id = target_vim.new_affinity_group(
                    affinity_group_data
                )
                created = True

            ro_vim_item_update = {
                "vim_id": affinity_group_vim_id,
                "vim_status": "ACTIVE",
                "created": created,
                "created_items": created_items,
                "vim_details": None,
                "vim_message": None,
            }
            self.logger.debug(
                "task={} {} new-affinity-or-anti-affinity-group={} created={}".format(
                    task_id, ro_task["target_id"], affinity_group_vim_id, created
                )
            )

            return "DONE", ro_vim_item_update
        except (vimconn.VimConnException, NsWorkerException) as e:
            self.logger.error(
                "task={} vim={} new-affinity-or-anti-affinity-group:"
                " {}".format(task_id, ro_task["target_id"], e)
            )
            ro_vim_item_update = {
                "vim_status": "VIM_ERROR",
                "created": created,
                "vim_message": str(e),
            }

            return "FAILED", ro_vim_item_update


class VimInteractionUpdateVdu(VimInteractionBase):
    def exec(self, ro_task, task_index, task_depends):
        task = ro_task["tasks"][task_index]
        task_id = task["task_id"]
        db_task_update = {"retries": 0}
        target_vim = self.my_vims[ro_task["target_id"]]

        try:
            vim_vm_id = ""
            if task.get("params"):
                vim_vm_id = task["params"].get("vim_vm_id")
                action = task["params"].get("action")
                context = {action: action}
                target_vim.action_vminstance(vim_vm_id, context)
                # created = True
            ro_vim_item_update = {
                "vim_id": vim_vm_id,
                "vim_status": "ACTIVE",
            }
            self.logger.debug(
                "task={} {} vm-migration done".format(task_id, ro_task["target_id"])
            )
            return "DONE", ro_vim_item_update, db_task_update
        except (vimconn.VimConnException, NsWorkerException) as e:
            self.logger.error(
                "task={} vim={} VM Migration:"
                " {}".format(task_id, ro_task["target_id"], e)
            )
            ro_vim_item_update = {
                "vim_status": "VIM_ERROR",
                "vim_message": str(e),
            }

            return "FAILED", ro_vim_item_update, db_task_update


class VimInteractionSdnNet(VimInteractionBase):
    @staticmethod
    def _match_pci(port_pci, mapping):
        """
        Check if port_pci matches with mapping.
        The mapping can have brackets to indicate that several chars are accepted. e.g
        pci '0000:af:10.1' matches with '0000:af:1[01].[1357]'
        :param port_pci: text
        :param mapping: text, can contain brackets to indicate several chars are available
        :return: True if matches, False otherwise
        """
        if not port_pci or not mapping:
            return False
        if port_pci == mapping:
            return True

        mapping_index = 0
        pci_index = 0
        while True:
            bracket_start = mapping.find("[", mapping_index)

            if bracket_start == -1:
                break

            bracket_end = mapping.find("]", bracket_start)
            if bracket_end == -1:
                break

            length = bracket_start - mapping_index
            if (
                length
                and port_pci[pci_index : pci_index + length]
                != mapping[mapping_index:bracket_start]
            ):
                return False

            if (
                port_pci[pci_index + length]
                not in mapping[bracket_start + 1 : bracket_end]
            ):
                return False

            pci_index += length + 1
            mapping_index = bracket_end + 1

        if port_pci[pci_index:] != mapping[mapping_index:]:
            return False

        return True

    def _get_interfaces(self, vlds_to_connect, vim_account_id):
        """
        :param vlds_to_connect: list with format vnfrs:<id>:vld.<vld_id> or nsrs:<id>:vld.<vld_id>
        :param vim_account_id:
        :return:
        """
        interfaces = []

        for vld in vlds_to_connect:
            table, _, db_id = vld.partition(":")
            db_id, _, vld = db_id.partition(":")
            _, _, vld_id = vld.partition(".")

            if table == "vnfrs":
                q_filter = {"vim-account-id": vim_account_id, "_id": db_id}
                iface_key = "vnf-vld-id"
            else:  # table == "nsrs"
                q_filter = {"vim-account-id": vim_account_id, "nsr-id-ref": db_id}
                iface_key = "ns-vld-id"

            db_vnfrs = self.db.get_list("vnfrs", q_filter=q_filter)

            for db_vnfr in db_vnfrs:
                for vdu_index, vdur in enumerate(db_vnfr.get("vdur", ())):
                    for iface_index, interface in enumerate(vdur["interfaces"]):
                        if interface.get(iface_key) == vld_id and interface.get(
                            "type"
                        ) in ("SR-IOV", "PCI-PASSTHROUGH"):
                            # only SR-IOV o PT
                            interface_ = interface.copy()
                            interface_["id"] = "vnfrs:{}:vdu.{}.interfaces.{}".format(
                                db_vnfr["_id"], vdu_index, iface_index
                            )

                            if vdur.get("status") == "ERROR":
                                interface_["status"] = "ERROR"

                            interfaces.append(interface_)

        return interfaces

    def refresh(self, ro_task):
        # look for task create
        task_create_index, _ = next(
            i_t
            for i_t in enumerate(ro_task["tasks"])
            if i_t[1]
            and i_t[1]["action"] == "CREATE"
            and i_t[1]["status"] != "FINISHED"
        )

        return self.new(ro_task, task_create_index, None)

    def new(self, ro_task, task_index, task_depends):
        task = ro_task["tasks"][task_index]
        task_id = task["task_id"]
        target_vim = self.my_vims[ro_task["target_id"]]

        sdn_net_id = ro_task["vim_info"]["vim_id"]

        created_items = ro_task["vim_info"].get("created_items")
        connected_ports = ro_task["vim_info"].get("connected_ports", [])
        new_connected_ports = []
        last_update = ro_task["vim_info"].get("last_update", 0)
        sdn_status = ro_task["vim_info"].get("vim_status", "BUILD") or "BUILD"
        error_list = []
        created = ro_task["vim_info"].get("created", False)

        try:
            # CREATE
            db_vim = {}
            params = task["params"]
            vlds_to_connect = params.get("vlds", [])
            associated_vim = params.get("target_vim")
            # external additional ports
            additional_ports = params.get("sdn-ports") or ()
            _, _, vim_account_id = (
                (None, None, None)
                if associated_vim is None
                else associated_vim.partition(":")
            )

            if associated_vim:
                # get associated VIM
                if associated_vim not in self.db_vims:
                    self.db_vims[associated_vim] = self.db.get_one(
                        "vim_accounts", {"_id": vim_account_id}
                    )

                db_vim = self.db_vims[associated_vim]

            # look for ports to connect
            ports = self._get_interfaces(vlds_to_connect, vim_account_id)
            # print(ports)

            sdn_ports = []
            pending_ports = error_ports = 0
            vlan_used = None
            sdn_need_update = False

            for port in ports:
                vlan_used = port.get("vlan") or vlan_used

                # TODO. Do not connect if already done
                if not port.get("compute_node") or not port.get("pci"):
                    if port.get("status") == "ERROR":
                        error_ports += 1
                    else:
                        pending_ports += 1
                    continue

                pmap = None
                compute_node_mappings = next(
                    (
                        c
                        for c in db_vim["config"].get("sdn-port-mapping", ())
                        if c and c["compute_node"] == port["compute_node"]
                    ),
                    None,
                )

                if compute_node_mappings:
                    # process port_mapping pci of type 0000:af:1[01].[1357]
                    pmap = next(
                        (
                            p
                            for p in compute_node_mappings["ports"]
                            if self._match_pci(port["pci"], p.get("pci"))
                        ),
                        None,
                    )

                if not pmap:
                    if not db_vim["config"].get("mapping_not_needed"):
                        error_list.append(
                            "Port mapping not found for compute_node={} pci={}".format(
                                port["compute_node"], port["pci"]
                            )
                        )
                        continue

                    pmap = {}

                service_endpoint_id = "{}:{}".format(port["compute_node"], port["pci"])
                new_port = {
                    "service_endpoint_id": pmap.get("service_endpoint_id")
                    or service_endpoint_id,
                    "service_endpoint_encapsulation_type": (
                        "dot1q" if port["type"] == "SR-IOV" else None
                    ),
                    "service_endpoint_encapsulation_info": {
                        "vlan": port.get("vlan"),
                        "mac": port.get("mac-address"),
                        "device_id": pmap.get("device_id") or port["compute_node"],
                        "device_interface_id": pmap.get("device_interface_id")
                        or port["pci"],
                        "switch_dpid": pmap.get("switch_id") or pmap.get("switch_dpid"),
                        "switch_port": pmap.get("switch_port"),
                        "service_mapping_info": pmap.get("service_mapping_info"),
                    },
                }

                # TODO
                # if port["modified_at"] > last_update:
                #     sdn_need_update = True
                new_connected_ports.append(port["id"])  # TODO
                sdn_ports.append(new_port)

            if error_ports:
                error_list.append(
                    "{} interfaces have not been created as VDU is on ERROR status".format(
                        error_ports
                    )
                )

            # connect external ports
            for index, additional_port in enumerate(additional_ports):
                additional_port_id = additional_port.get(
                    "service_endpoint_id"
                ) or "external-{}".format(index)
                sdn_ports.append(
                    {
                        "service_endpoint_id": additional_port_id,
                        "service_endpoint_encapsulation_type": additional_port.get(
                            "service_endpoint_encapsulation_type", "dot1q"
                        ),
                        "service_endpoint_encapsulation_info": {
                            "vlan": additional_port.get("vlan") or vlan_used,
                            "mac": additional_port.get("mac_address"),
                            "device_id": additional_port.get("device_id"),
                            "device_interface_id": additional_port.get(
                                "device_interface_id"
                            ),
                            "switch_dpid": additional_port.get("switch_dpid")
                            or additional_port.get("switch_id"),
                            "switch_port": additional_port.get("switch_port"),
                            "service_mapping_info": additional_port.get(
                                "service_mapping_info"
                            ),
                        },
                    }
                )
                new_connected_ports.append(additional_port_id)
            sdn_info = ""

            # if there are more ports to connect or they have been modified, call create/update
            if error_list:
                sdn_status = "ERROR"
                sdn_info = "; ".join(error_list)
            elif set(connected_ports) != set(new_connected_ports) or sdn_need_update:
                last_update = time.time()

                if not sdn_net_id:
                    if len(sdn_ports) < 2:
                        sdn_status = "ACTIVE"

                        if not pending_ports:
                            self.logger.debug(
                                "task={} {} new-sdn-net done, less than 2 ports".format(
                                    task_id, ro_task["target_id"]
                                )
                            )
                    else:
                        net_type = params.get("type") or "ELAN"
                        (
                            sdn_net_id,
                            created_items,
                        ) = target_vim.create_connectivity_service(net_type, sdn_ports)
                        created = True
                        self.logger.debug(
                            "task={} {} new-sdn-net={} created={}".format(
                                task_id, ro_task["target_id"], sdn_net_id, created
                            )
                        )
                else:
                    created_items = target_vim.edit_connectivity_service(
                        sdn_net_id, conn_info=created_items, connection_points=sdn_ports
                    )
                    created = True
                    self.logger.debug(
                        "task={} {} update-sdn-net={} created={}".format(
                            task_id, ro_task["target_id"], sdn_net_id, created
                        )
                    )

                connected_ports = new_connected_ports
            elif sdn_net_id:
                wim_status_dict = target_vim.get_connectivity_service_status(
                    sdn_net_id, conn_info=created_items
                )
                sdn_status = wim_status_dict["sdn_status"]

                if wim_status_dict.get("sdn_info"):
                    sdn_info = str(wim_status_dict.get("sdn_info")) or ""

                if wim_status_dict.get("error_msg"):
                    sdn_info = wim_status_dict.get("error_msg") or ""

            if pending_ports:
                if sdn_status != "ERROR":
                    sdn_info = "Waiting for getting interfaces location from VIM. Obtained '{}' of {}".format(
                        len(ports) - pending_ports, len(ports)
                    )

                if sdn_status == "ACTIVE":
                    sdn_status = "BUILD"

            ro_vim_item_update = {
                "vim_id": sdn_net_id,
                "vim_status": sdn_status,
                "created": created,
                "created_items": created_items,
                "connected_ports": connected_ports,
                "vim_details": sdn_info,
                "vim_message": None,
                "last_update": last_update,
            }

            return sdn_status, ro_vim_item_update
        except Exception as e:
            self.logger.error(
                "task={} vim={} new-net: {}".format(task_id, ro_task["target_id"], e),
                exc_info=not isinstance(
                    e, (sdnconn.SdnConnectorError, vimconn.VimConnException)
                ),
            )
            ro_vim_item_update = {
                "vim_status": "VIM_ERROR",
                "created": created,
                "vim_message": str(e),
            }

            return "FAILED", ro_vim_item_update

    def delete(self, ro_task, task_index):
        task = ro_task["tasks"][task_index]
        task_id = task["task_id"]
        sdn_vim_id = ro_task["vim_info"].get("vim_id")
        ro_vim_item_update_ok = {
            "vim_status": "DELETED",
            "created": False,
            "vim_message": "DELETED",
            "vim_id": None,
        }

        try:
            if sdn_vim_id:
                target_vim = self.my_vims[ro_task["target_id"]]
                target_vim.delete_connectivity_service(
                    sdn_vim_id, ro_task["vim_info"].get("created_items")
                )

        except Exception as e:
            if (
                isinstance(e, sdnconn.SdnConnectorError)
                and e.http_code == HTTPStatus.NOT_FOUND.value
            ):
                ro_vim_item_update_ok["vim_message"] = "already deleted"
            else:
                self.logger.error(
                    "ro_task={} vim={} del-sdn-net={}: {}".format(
                        ro_task["_id"], ro_task["target_id"], sdn_vim_id, e
                    ),
                    exc_info=not isinstance(
                        e, (sdnconn.SdnConnectorError, vimconn.VimConnException)
                    ),
                )
                ro_vim_item_update = {
                    "vim_status": "VIM_ERROR",
                    "vim_message": "Error while deleting: {}".format(e),
                }

                return "FAILED", ro_vim_item_update

        self.logger.debug(
            "task={} {} del-sdn-net={} {}".format(
                task_id,
                ro_task["target_id"],
                sdn_vim_id,
                ro_vim_item_update_ok.get("vim_message", ""),
            )
        )

        return "DONE", ro_vim_item_update_ok


class VimInteractionMigration(VimInteractionBase):
    def exec(self, ro_task, task_index, task_depends):
        task = ro_task["tasks"][task_index]
        task_id = task["task_id"]
        db_task_update = {"retries": 0}
        target_vim = self.my_vims[ro_task["target_id"]]
        vim_interfaces = []
        refreshed_vim_info = {}

        try:
            vim_vm_id = ""
            if task.get("params"):
                vim_vm_id = task["params"].get("vim_vm_id")
                migrate_host = task["params"].get("migrate_host")
                _, migrated_compute_node = target_vim.migrate_instance(
                    vim_vm_id, migrate_host
                )

                if migrated_compute_node:
                    # When VM is migrated, vdu["vim_info"] needs to be updated
                    vdu_old_vim_info = task["params"]["vdu_vim_info"].get(
                        ro_task["target_id"]
                    )

                    # Refresh VM to get new vim_info
                    vm_to_refresh_list = [vim_vm_id]
                    vim_dict = target_vim.refresh_vms_status(vm_to_refresh_list)
                    refreshed_vim_info = vim_dict[vim_vm_id]

                    if refreshed_vim_info.get("interfaces"):
                        for old_iface in vdu_old_vim_info.get("interfaces"):
                            iface = next(
                                (
                                    iface
                                    for iface in refreshed_vim_info["interfaces"]
                                    if old_iface["vim_interface_id"]
                                    == iface["vim_interface_id"]
                                ),
                                None,
                            )
                            vim_interfaces.append(iface)

            ro_vim_item_update = {
                "vim_id": vim_vm_id,
                "vim_status": "ACTIVE",
                "vim_details": None,
                "vim_message": None,
            }

            if refreshed_vim_info and refreshed_vim_info.get("status") not in (
                "ERROR",
                "VIM_ERROR",
            ):
                ro_vim_item_update["vim_details"] = refreshed_vim_info["vim_info"]

            if vim_interfaces:
                ro_vim_item_update["interfaces"] = vim_interfaces

            self.logger.debug(
                "task={} {} vm-migration done".format(task_id, ro_task["target_id"])
            )

            return "DONE", ro_vim_item_update, db_task_update

        except (vimconn.VimConnException, NsWorkerException) as e:
            self.logger.error(
                "task={} vim={} VM Migration:"
                " {}".format(task_id, ro_task["target_id"], e)
            )
            ro_vim_item_update = {
                "vim_status": "VIM_ERROR",
                "vim_message": str(e),
            }

            return "FAILED", ro_vim_item_update, db_task_update


class VimInteractionResize(VimInteractionBase):
    def exec(self, ro_task, task_index, task_depends):
        task = ro_task["tasks"][task_index]
        task_id = task["task_id"]
        db_task_update = {"retries": 0}
        target_flavor_uuid = None
        refreshed_vim_info = {}
        target_vim = self.my_vims[ro_task["target_id"]]

        try:
            params = task["params"]
            params_copy = deepcopy(params)
            target_flavor_uuid = task_depends[params_copy["flavor_id"]]
            vim_vm_id = ""
            if task.get("params"):
                self.logger.info("vim_vm_id %s", vim_vm_id)

                if target_flavor_uuid is not None:
                    resized_status = target_vim.resize_instance(
                        vim_vm_id, target_flavor_uuid
                    )

                    if resized_status:
                        # Refresh VM to get new vim_info
                        vm_to_refresh_list = [vim_vm_id]
                        vim_dict = target_vim.refresh_vms_status(vm_to_refresh_list)
                        refreshed_vim_info = vim_dict[vim_vm_id]

            ro_vim_item_update = {
                "vim_id": vim_vm_id,
                "vim_status": "ACTIVE",
                "vim_details": None,
                "vim_message": None,
            }

            if refreshed_vim_info and refreshed_vim_info.get("status") not in (
                "ERROR",
                "VIM_ERROR",
            ):
                ro_vim_item_update["vim_details"] = refreshed_vim_info["vim_info"]

            self.logger.debug(
                "task={} {} resize done".format(task_id, ro_task["target_id"])
            )
            return "DONE", ro_vim_item_update, db_task_update
        except (vimconn.VimConnException, NsWorkerException) as e:
            self.logger.error(
                "task={} vim={} Resize:" " {}".format(task_id, ro_task["target_id"], e)
            )
            ro_vim_item_update = {
                "vim_status": "VIM_ERROR",
                "vim_message": str(e),
            }

            return "FAILED", ro_vim_item_update, db_task_update


class ConfigValidate:
    def __init__(self, config: Dict):
        self.conf = config

    @property
    def active(self):
        # default 1 min, allowed >= 60 or -1, -1 disables periodic checks
        if (
            self.conf["period"]["refresh_active"] >= 60
            or self.conf["period"]["refresh_active"] == -1
        ):
            return self.conf["period"]["refresh_active"]

        return 60

    @property
    def build(self):
        return self.conf["period"]["refresh_build"]

    @property
    def image(self):
        return self.conf["period"]["refresh_image"]

    @property
    def error(self):
        return self.conf["period"]["refresh_error"]

    @property
    def queue_size(self):
        return self.conf["period"]["queue_size"]


class NsWorker(threading.Thread):
    def __init__(self, worker_index, config, plugins, db):
        """
        :param worker_index: thread index
        :param config: general configuration of RO, among others the process_id with the docker id where it runs
        :param plugins: global shared dict with the loaded plugins
        :param db: database class instance to use
        """
        threading.Thread.__init__(self)
        self.config = config
        self.plugins = plugins
        self.plugin_name = "unknown"
        self.logger = logging.getLogger("ro.worker{}".format(worker_index))
        self.worker_index = worker_index
        # refresh periods for created items
        self.refresh_config = ConfigValidate(config)
        self.task_queue = queue.Queue(self.refresh_config.queue_size)
        # targetvim: vimplugin class
        self.my_vims = {}
        # targetvim: vim information from database
        self.db_vims = {}
        # targetvim list
        self.vim_targets = []
        self.my_id = config["process_id"] + ":" + str(worker_index)
        self.db = db
        self.item2class = {
            "net": VimInteractionNet(self.db, self.my_vims, self.db_vims, self.logger),
            "shared-volumes": VimInteractionSharedVolume(
                self.db, self.my_vims, self.db_vims, self.logger
            ),
            "classification": VimInteractionClassification(
                self.db, self.my_vims, self.db_vims, self.logger
            ),
            "sfi": VimInteractionSfi(self.db, self.my_vims, self.db_vims, self.logger),
            "sf": VimInteractionSf(self.db, self.my_vims, self.db_vims, self.logger),
            "sfp": VimInteractionSfp(self.db, self.my_vims, self.db_vims, self.logger),
            "vdu": VimInteractionVdu(self.db, self.my_vims, self.db_vims, self.logger),
            "image": VimInteractionImage(
                self.db, self.my_vims, self.db_vims, self.logger
            ),
            "flavor": VimInteractionFlavor(
                self.db, self.my_vims, self.db_vims, self.logger
            ),
            "sdn_net": VimInteractionSdnNet(
                self.db, self.my_vims, self.db_vims, self.logger
            ),
            "update": VimInteractionUpdateVdu(
                self.db, self.my_vims, self.db_vims, self.logger
            ),
            "affinity-or-anti-affinity-group": VimInteractionAffinityGroup(
                self.db, self.my_vims, self.db_vims, self.logger
            ),
            "migrate": VimInteractionMigration(
                self.db, self.my_vims, self.db_vims, self.logger
            ),
            "verticalscale": VimInteractionResize(
                self.db, self.my_vims, self.db_vims, self.logger
            ),
        }
        self.time_last_task_processed = None
        # lists of tasks to delete because nsrs or vnfrs has been deleted from db
        self.tasks_to_delete = []
        # it is idle when there are not vim_targets associated
        self.idle = True
        self.task_locked_time = config["global"]["task_locked_time"]

    def insert_task(self, task):
        try:
            self.task_queue.put(task, False)
            return None
        except queue.Full:
            raise NsWorkerException("timeout inserting a task")

    def terminate(self):
        self.insert_task("exit")

    def del_task(self, task):
        with self.task_lock:
            if task["status"] == "SCHEDULED":
                task["status"] = "SUPERSEDED"
                return True
            else:  # task["status"] == "processing"
                self.task_lock.release()
                return False

    def _process_vim_config(self, target_id: str, db_vim: dict) -> None:
        """
        Process vim config, creating vim configuration files as ca_cert
        :param target_id: vim/sdn/wim + id
        :param db_vim: Vim dictionary obtained from database
        :return: None. Modifies vim. Creates a folder target_id:worker_index and several files
        """
        if not db_vim.get("config"):
            return

        file_name = ""
        work_dir = "/app/osm_ro/certs"

        try:
            if db_vim["config"].get("ca_cert_content"):
                file_name = f"{work_dir}/{target_id}:{self.worker_index}"

                if not path.isdir(file_name):
                    makedirs(file_name)

                file_name = file_name + "/ca_cert"

                with open(file_name, "w") as f:
                    f.write(db_vim["config"]["ca_cert_content"])
                    del db_vim["config"]["ca_cert_content"]
                    db_vim["config"]["ca_cert"] = file_name
        except Exception as e:
            raise NsWorkerException(
                "Error writing to file '{}': {}".format(file_name, e)
            )

    def _load_plugin(self, name, type="vim"):
        # type can be vim or sdn
        if "rovim_dummy" not in self.plugins:
            self.plugins["rovim_dummy"] = VimDummyConnector

        if "rosdn_dummy" not in self.plugins:
            self.plugins["rosdn_dummy"] = SdnDummyConnector

        if name in self.plugins:
            return self.plugins[name]

        try:
            for ep in entry_points(group="osm_ro{}.plugins".format(type), name=name):
                self.plugins[name] = ep.load()
        except Exception as e:
            raise NsWorkerException("Cannot load plugin osm_{}: {}".format(name, e))

        if name and name not in self.plugins:
            raise NsWorkerException(
                "Plugin 'osm_{n}' has not been installed".format(n=name)
            )

        return self.plugins[name]

    def _unload_vim(self, target_id):
        """
        Unload a vim_account. Removes it from self db_vims dictionary, my_vims dictionary and vim_targets list
        :param target_id: Contains type:_id; where type can be 'vim', ...
        :return: None.
        """
        try:
            self.db_vims.pop(target_id, None)
            self.my_vims.pop(target_id, None)

            if target_id in self.vim_targets:
                self.vim_targets.remove(target_id)

            self.logger.info("Unloaded {}".format(target_id))
        except Exception as e:
            self.logger.error("Cannot unload {}: {}".format(target_id, e))

    def _check_vim(self, target_id):
        """
        Load a VIM/SDN/WIM (if not loaded) and check connectivity, updating database with ENABLE or ERROR
        :param target_id: Contains type:_id; type can be 'vim', 'sdn' or 'wim'
        :return: None.
        """
        target, _, _id = target_id.partition(":")
        now = time.time()
        update_dict = {}
        unset_dict = {}
        op_text = ""
        step = ""
        loaded = target_id in self.vim_targets
        target_database = (
            "vim_accounts"
            if target == "vim"
            else "wim_accounts" if target == "wim" else "sdns"
        )
        error_text = ""

        try:
            step = "Getting {} from db".format(target_id)
            db_vim = self.db.get_one(target_database, {"_id": _id})

            for op_index, operation in enumerate(
                db_vim["_admin"].get("operations", ())
            ):
                if operation["operationState"] != "PROCESSING":
                    continue

                locked_at = operation.get("locked_at")

                if locked_at is not None and locked_at >= now - self.task_locked_time:
                    # some other thread is doing this operation
                    return

                # lock
                op_text = "_admin.operations.{}.".format(op_index)

                if not self.db.set_one(
                    target_database,
                    q_filter={
                        "_id": _id,
                        op_text + "operationState": "PROCESSING",
                        op_text + "locked_at": locked_at,
                    },
                    update_dict={
                        op_text + "locked_at": now,
                        "admin.current_operation": op_index,
                    },
                    fail_on_empty=False,
                ):
                    return

                unset_dict[op_text + "locked_at"] = None
                unset_dict["current_operation"] = None
                step = "Loading " + target_id
                error_text = self._load_vim(target_id)

                if not error_text:
                    step = "Checking connectivity"

                    if target == "vim":
                        self.my_vims[target_id].check_vim_connectivity()
                    else:
                        self.my_vims[target_id].check_credentials()

                update_dict["_admin.operationalState"] = "ENABLED"
                update_dict["_admin.detailed-status"] = ""
                unset_dict[op_text + "detailed-status"] = None
                update_dict[op_text + "operationState"] = "COMPLETED"

                return

        except Exception as e:
            error_text = "{}: {}".format(step, e)
            self.logger.error("{} for {}: {}".format(step, target_id, e))

        finally:
            if update_dict or unset_dict:
                if error_text:
                    update_dict[op_text + "operationState"] = "FAILED"
                    update_dict[op_text + "detailed-status"] = error_text
                    unset_dict.pop(op_text + "detailed-status", None)
                    update_dict["_admin.operationalState"] = "ERROR"
                    update_dict["_admin.detailed-status"] = error_text

                if op_text:
                    update_dict[op_text + "statusEnteredTime"] = now

                self.db.set_one(
                    target_database,
                    q_filter={"_id": _id},
                    update_dict=update_dict,
                    unset=unset_dict,
                    fail_on_empty=False,
                )

            if not loaded:
                self._unload_vim(target_id)

    def _reload_vim(self, target_id):
        if target_id in self.vim_targets:
            self._load_vim(target_id)
        else:
            # if the vim is not loaded, but database information of VIM is cached at self.db_vims,
            # just remove it to force load again next time it is needed
            self.db_vims.pop(target_id, None)

    def _load_vim(self, target_id):
        """
        Load or reload a vim_account, sdn_controller or wim_account.
        Read content from database, load the plugin if not loaded.
        In case of error loading the plugin, it loads a failing VIM_connector
        It fills self db_vims dictionary, my_vims dictionary and vim_targets list
        :param target_id: Contains type:_id; where type can be 'vim', ...
        :return: None if ok, descriptive text if error
        """
        target, _, _id = target_id.partition(":")
        target_database = (
            "vim_accounts"
            if target == "vim"
            else "wim_accounts" if target == "wim" else "sdns"
        )
        plugin_name = ""
        vim = None
        step = "Getting {}={} from db".format(target, _id)

        try:
            # TODO process for wim, sdnc, ...
            vim = self.db.get_one(target_database, {"_id": _id})

            # if deep_get(vim, "config", "sdn-controller"):
            #     step = "Getting sdn-controller-id='{}' from db".format(vim["config"]["sdn-controller"])
            #     db_sdn = self.db.get_one("sdns", {"_id": vim["config"]["sdn-controller"]})

            step = "Decrypting password"
            schema_version = vim.get("schema_version")
            self.db.encrypt_decrypt_fields(
                vim,
                "decrypt",
                fields=("password", "secret"),
                schema_version=schema_version,
                salt=_id,
            )
            self._process_vim_config(target_id, vim)

            if target == "vim":
                plugin_name = "rovim_" + vim["vim_type"]
                step = "Loading plugin '{}'".format(plugin_name)
                vim_module_conn = self._load_plugin(plugin_name)
                step = "Loading {}'".format(target_id)
                self.my_vims[target_id] = vim_module_conn(
                    uuid=vim["_id"],
                    name=vim["name"],
                    tenant_id=vim.get("vim_tenant_id"),
                    tenant_name=vim.get("vim_tenant_name"),
                    url=vim["vim_url"],
                    url_admin=None,
                    user=vim["vim_user"],
                    passwd=vim["vim_password"],
                    config=vim.get("config") or {},
                    persistent_info={},
                )
            else:  # sdn
                plugin_name = "rosdn_" + (vim.get("type") or vim.get("wim_type"))
                step = "Loading plugin '{}'".format(plugin_name)
                vim_module_conn = self._load_plugin(plugin_name, "sdn")
                step = "Loading {}'".format(target_id)
                wim = deepcopy(vim)
                wim_config = wim.pop("config", {}) or {}
                wim["uuid"] = wim["_id"]
                if "url" in wim and "wim_url" not in wim:
                    wim["wim_url"] = wim["url"]
                elif "url" not in wim and "wim_url" in wim:
                    wim["url"] = wim["wim_url"]

                if wim.get("dpid"):
                    wim_config["dpid"] = wim.pop("dpid")

                if wim.get("switch_id"):
                    wim_config["switch_id"] = wim.pop("switch_id")

                # wim, wim_account, config
                self.my_vims[target_id] = vim_module_conn(wim, wim, wim_config)
            self.db_vims[target_id] = vim
            self.error_status = None

            self.logger.info(
                "Connector loaded for {}, plugin={}".format(target_id, plugin_name)
            )
        except Exception as e:
            self.logger.error(
                "Cannot load {} plugin={}: {} {}".format(
                    target_id, plugin_name, step, e
                )
            )

            self.db_vims[target_id] = vim or {}
            self.db_vims[target_id] = FailingConnector(str(e))
            error_status = "{} Error: {}".format(step, e)

            return error_status
        finally:
            if target_id not in self.vim_targets:
                self.vim_targets.append(target_id)

    def _get_db_task(self):
        """
        Read actions from database and reload them at memory. Fill self.refresh_list, pending_list, vim_actions
        :return: None
        """
        now = time.time()

        if not self.time_last_task_processed:
            self.time_last_task_processed = now

        try:
            while True:
                """
                # Log RO tasks only when loglevel is DEBUG
                if self.logger.getEffectiveLevel() == logging.DEBUG:
                    self._log_ro_task(
                        None,
                        None,
                        None,
                        "TASK_WF",
                        "task_locked_time="
                        + str(self.task_locked_time)
                        + " "
                        + "time_last_task_processed="
                        + str(self.time_last_task_processed)
                        + " "
                        + "now="
                        + str(now),
                    )
                """
                locked = self.db.set_one(
                    "ro_tasks",
                    q_filter={
                        "target_id": self.vim_targets,
                        "tasks.status": ["SCHEDULED", "BUILD", "DONE", "FAILED"],
                        "locked_at.lt": now - self.task_locked_time,
                        "to_check_at.lt": self.time_last_task_processed,
                        "to_check_at.gt": -1,
                    },
                    update_dict={"locked_by": self.my_id, "locked_at": now},
                    fail_on_empty=False,
                )

                if locked:
                    # read and return
                    ro_task = self.db.get_one(
                        "ro_tasks",
                        q_filter={
                            "target_id": self.vim_targets,
                            "tasks.status": ["SCHEDULED", "BUILD", "DONE", "FAILED"],
                            "locked_at": now,
                        },
                    )
                    return ro_task

                if self.time_last_task_processed == now:
                    self.time_last_task_processed = None
                    return None
                else:
                    self.time_last_task_processed = now
                    # self.time_last_task_processed = min(self.time_last_task_processed + 1000, now)

        except DbException as e:
            self.logger.error("Database exception at _get_db_task: {}".format(e))
        except Exception as e:
            self.logger.critical(
                "Unexpected exception at _get_db_task: {}".format(e), exc_info=True
            )

        return None

    def _delete_task(self, ro_task, task_index, task_depends, db_update):
        """
        Determine if this task need to be done or superseded
        :return: None
        """
        my_task = ro_task["tasks"][task_index]
        task_id = my_task["task_id"]
        needed_delete = ro_task["vim_info"]["created"] or ro_task["vim_info"].get(
            "created_items", False
        )

        self.logger.debug("Needed delete: {}".format(needed_delete))
        if my_task["status"] == "FAILED":
            return None, None  # TODO need to be retry??

        try:
            for index, task in enumerate(ro_task["tasks"]):
                if index == task_index or not task:
                    continue  # own task

                if (
                    my_task["target_record"] == task["target_record"]
                    and task["action"] == "CREATE"
                ):
                    # set to finished
                    db_update["tasks.{}.status".format(index)] = task["status"] = (
                        "FINISHED"
                    )
                elif task["action"] == "CREATE" and task["status"] not in (
                    "FINISHED",
                    "SUPERSEDED",
                ):
                    needed_delete = False

            if needed_delete:
                self.logger.debug(
                    "Deleting ro_task={} task_index={}".format(ro_task, task_index)
                )
                return self.item2class[my_task["item"]].delete(ro_task, task_index)
            else:
                return "SUPERSEDED", None
        except Exception as e:
            if not isinstance(e, NsWorkerException):
                self.logger.critical(
                    "Unexpected exception at _delete_task task={}: {}".format(
                        task_id, e
                    ),
                    exc_info=True,
                )

            return "FAILED", {"vim_status": "VIM_ERROR", "vim_message": str(e)}

    def _create_task(self, ro_task, task_index, task_depends, db_update):
        """
        Determine if this task need to create something at VIM
        :return: None
        """
        my_task = ro_task["tasks"][task_index]
        task_id = my_task["task_id"]

        if my_task["status"] == "FAILED":
            return None, None  # TODO need to be retry??
        elif my_task["status"] == "SCHEDULED":
            # check if already created by another task
            for index, task in enumerate(ro_task["tasks"]):
                if index == task_index or not task:
                    continue  # own task

                if task["action"] == "CREATE" and task["status"] not in (
                    "SCHEDULED",
                    "FINISHED",
                    "SUPERSEDED",
                ):
                    return task["status"], "COPY_VIM_INFO"

            try:
                task_status, ro_vim_item_update = self.item2class[my_task["item"]].new(
                    ro_task, task_index, task_depends
                )
                # TODO update other CREATE tasks
            except Exception as e:
                if not isinstance(e, NsWorkerException):
                    self.logger.error(
                        "Error executing task={}: {}".format(task_id, e), exc_info=True
                    )

                task_status = "FAILED"
                ro_vim_item_update = {"vim_status": "VIM_ERROR", "vim_message": str(e)}
                # TODO update    ro_vim_item_update

            return task_status, ro_vim_item_update
        else:
            return None, None

    def _get_dependency(self, task_id, ro_task=None, target_id=None):
        """
        Look for dependency task
        :param task_id: Can be one of
            1. target_vim+blank+task.target_record_id: "(vim|sdn|wim):<id> (vnfrs|nsrs):(vld|vdu|flavor|image).<id>"
            2. task.target_record_id: "(vnfrs|nsrs):(vld|vdu|flavor|image).<id>"
            3. task.task_id: "<action_id>:number"
        :param ro_task:
        :param target_id:
        :return: database ro_task plus index of task
        """
        if (
            task_id.startswith("vim:")
            or task_id.startswith("sdn:")
            or task_id.startswith("wim:")
        ):
            target_id, _, task_id = task_id.partition(" ")

        if task_id.startswith("nsrs:") or task_id.startswith("vnfrs:"):
            ro_task_dependency = self.db.get_one(
                "ro_tasks",
                q_filter={"target_id": target_id, "tasks.target_record_id": task_id},
                fail_on_empty=False,
            )

            if ro_task_dependency:
                for task_index, task in enumerate(ro_task_dependency["tasks"]):
                    if task["target_record_id"] == task_id:
                        return ro_task_dependency, task_index

        else:
            if ro_task:
                for task_index, task in enumerate(ro_task["tasks"]):
                    if task and task["task_id"] == task_id:
                        return ro_task, task_index

            ro_task_dependency = self.db.get_one(
                "ro_tasks",
                q_filter={
                    "tasks.ANYINDEX.task_id": task_id,
                    "tasks.ANYINDEX.target_record.ne": None,
                },
                fail_on_empty=False,
            )

            self.logger.debug("ro_task_dependency={}".format(ro_task_dependency))
            if ro_task_dependency:
                for task_index, task in enumerate(ro_task_dependency["tasks"]):
                    if task["task_id"] == task_id:
                        return ro_task_dependency, task_index
        raise NsWorkerException("Cannot get depending task {}".format(task_id))

    def update_vm_refresh(self, ro_task):
        """Enables the VM status updates if self.refresh_config.active parameter
        is not -1 and then updates the DB accordingly

        """
        try:
            self.logger.debug("Checking if VM status update config")
            next_refresh = time.time()
            next_refresh = self._get_next_refresh(ro_task, next_refresh)

            if next_refresh != -1:
                db_ro_task_update = {}
                now = time.time()
                next_check_at = now + (24 * 60 * 60)
                next_check_at = min(next_check_at, next_refresh)
                db_ro_task_update["vim_info.refresh_at"] = next_refresh
                db_ro_task_update["to_check_at"] = next_check_at

                self.logger.debug(
                    "Finding tasks which to be updated to enable VM status updates"
                )
                refresh_tasks = self.db.get_list(
                    "ro_tasks",
                    q_filter={
                        "tasks.status": "DONE",
                        "to_check_at.lt": 0,
                    },
                )
                self.logger.debug("Updating tasks to change the to_check_at status")
                for task in refresh_tasks:
                    q_filter = {
                        "_id": task["_id"],
                    }
                    self.db.set_one(
                        "ro_tasks",
                        q_filter=q_filter,
                        update_dict=db_ro_task_update,
                        fail_on_empty=True,
                    )

        except Exception as e:
            self.logger.error(f"Error updating tasks to enable VM status updates: {e}")

    def _get_next_refresh(self, ro_task: dict, next_refresh: float):
        """Decide the next_refresh according to vim type and refresh config period.
        Args:
            ro_task (dict):             ro_task details
            next_refresh    (float):    next refresh time as epoch format

        Returns:
            next_refresh    (float)     -1 if vm updates are disabled or vim type is openstack.
        """
        target_vim = ro_task["target_id"]
        vim_type = self.db_vims[target_vim]["vim_type"]
        if self.refresh_config.active == -1 or vim_type == "openstack":
            next_refresh = -1
        else:
            next_refresh += self.refresh_config.active
        return next_refresh

    def _process_pending_tasks(self, ro_task):
        ro_task_id = ro_task["_id"]
        now = time.time()
        # one day
        next_check_at = now + (24 * 60 * 60)
        db_ro_task_update = {}

        def _update_refresh(new_status):
            # compute next_refresh
            nonlocal task
            nonlocal next_check_at
            nonlocal db_ro_task_update
            nonlocal ro_task

            next_refresh = time.time()

            if task["item"] in ("image", "flavor"):
                next_refresh += self.refresh_config.image
            elif new_status == "BUILD":
                next_refresh += self.refresh_config.build
            elif new_status == "DONE":
                next_refresh = self._get_next_refresh(ro_task, next_refresh)
            else:
                next_refresh += self.refresh_config.error

            next_check_at = min(next_check_at, next_refresh)
            db_ro_task_update["vim_info.refresh_at"] = next_refresh
            ro_task["vim_info"]["refresh_at"] = next_refresh

        try:
            """
            # Log RO tasks only when loglevel is DEBUG
            if self.logger.getEffectiveLevel() == logging.DEBUG:
                self._log_ro_task(ro_task, None, None, "TASK_WF", "GET_TASK")
            """
            # Check if vim status refresh is enabled again
            self.update_vm_refresh(ro_task)
            # 0: get task_status_create
            lock_object = None
            task_status_create = None
            task_create = next(
                (
                    t
                    for t in ro_task["tasks"]
                    if t
                    and t["action"] == "CREATE"
                    and t["status"] in ("BUILD", "DONE")
                ),
                None,
            )

            if task_create:
                task_status_create = task_create["status"]

            # 1: look for tasks in status SCHEDULED, or in status CREATE if action is  DONE or BUILD
            for task_action in ("DELETE", "CREATE", "EXEC"):
                db_vim_update = None
                new_status = None

                for task_index, task in enumerate(ro_task["tasks"]):
                    if not task:
                        continue  # task deleted

                    task_depends = {}
                    target_update = None

                    if (
                        (
                            task_action in ("DELETE", "EXEC")
                            and task["status"] not in ("SCHEDULED", "BUILD")
                        )
                        or task["action"] != task_action
                        or (
                            task_action == "CREATE"
                            and task["status"] in ("FINISHED", "SUPERSEDED")
                        )
                    ):
                        continue

                    task_path = "tasks.{}.status".format(task_index)
                    try:
                        db_vim_info_update = None
                        dependency_ro_task = {}

                        if task["status"] == "SCHEDULED":
                            # check if tasks that this depends on have been completed
                            dependency_not_completed = False

                            for dependency_task_id in task.get("depends_on") or ():
                                (
                                    dependency_ro_task,
                                    dependency_task_index,
                                ) = self._get_dependency(
                                    dependency_task_id, target_id=ro_task["target_id"]
                                )
                                dependency_task = dependency_ro_task["tasks"][
                                    dependency_task_index
                                ]
                                self.logger.debug(
                                    "dependency_ro_task={} dependency_task_index={}".format(
                                        dependency_ro_task, dependency_task_index
                                    )
                                )

                                if dependency_task["status"] == "SCHEDULED":
                                    dependency_not_completed = True
                                    next_check_at = min(
                                        next_check_at, dependency_ro_task["to_check_at"]
                                    )
                                    # must allow dependent task to be processed first
                                    # to do this set time after last_task_processed
                                    next_check_at = max(
                                        self.time_last_task_processed, next_check_at
                                    )
                                    break
                                elif dependency_task["status"] == "FAILED":
                                    error_text = "Cannot {} {} because depends on failed {} {} id={}): {}".format(
                                        task["action"],
                                        task["item"],
                                        dependency_task["action"],
                                        dependency_task["item"],
                                        dependency_task_id,
                                        dependency_ro_task["vim_info"].get(
                                            "vim_message"
                                        ),
                                    )
                                    self.logger.error(
                                        "task={} {}".format(task["task_id"], error_text)
                                    )
                                    raise NsWorkerException(error_text)

                                task_depends[dependency_task_id] = dependency_ro_task[
                                    "vim_info"
                                ]["vim_id"]
                                task_depends["TASK-{}".format(dependency_task_id)] = (
                                    dependency_ro_task["vim_info"]["vim_id"]
                                )

                            if dependency_not_completed:
                                self.logger.warning(
                                    "DEPENDENCY NOT COMPLETED {}".format(
                                        dependency_ro_task["vim_info"]["vim_id"]
                                    )
                                )
                                # TODO set at vim_info.vim_details that it is waiting
                                continue

                        # before calling VIM-plugin as it can take more than task_locked_time, insert to LockRenew
                        # the task of renew this locking. It will update database locket_at periodically
                        if not lock_object:
                            lock_object = LockRenew.add_lock_object(
                                "ro_tasks", ro_task, self
                            )
                        if task["action"] == "DELETE":
                            (
                                new_status,
                                db_vim_info_update,
                            ) = self._delete_task(
                                ro_task, task_index, task_depends, db_ro_task_update
                            )
                            new_status = (
                                "FINISHED" if new_status == "DONE" else new_status
                            )
                            # ^with FINISHED instead of DONE it will not be refreshing

                            if new_status in ("FINISHED", "SUPERSEDED"):
                                target_update = "DELETE"
                        elif task["action"] == "EXEC":
                            (
                                new_status,
                                db_vim_info_update,
                                db_task_update,
                            ) = self.item2class[task["item"]].exec(
                                ro_task, task_index, task_depends
                            )
                            new_status = (
                                "FINISHED" if new_status == "DONE" else new_status
                            )
                            # ^with FINISHED instead of DONE it will not be refreshing

                            if db_task_update:
                                # load into database the modified db_task_update "retries" and "next_retry"
                                if db_task_update.get("retries"):
                                    db_ro_task_update[
                                        "tasks.{}.retries".format(task_index)
                                    ] = db_task_update["retries"]

                                next_check_at = time.time() + db_task_update.get(
                                    "next_retry", 60
                                )
                            target_update = None
                        elif task["action"] == "CREATE":
                            if task["status"] == "SCHEDULED":
                                if task_status_create:
                                    new_status = task_status_create
                                    target_update = "COPY_VIM_INFO"
                                else:
                                    new_status, db_vim_info_update = self.item2class[
                                        task["item"]
                                    ].new(ro_task, task_index, task_depends)
                                    _update_refresh(new_status)
                            else:
                                refresh_at = ro_task["vim_info"]["refresh_at"]
                                if refresh_at and refresh_at != -1 and now > refresh_at:
                                    (
                                        new_status,
                                        db_vim_info_update,
                                    ) = self.item2class[
                                        task["item"]
                                    ].refresh(ro_task)
                                    _update_refresh(new_status)
                                else:
                                    # The refresh is updated to avoid set the value of "refresh_at" to
                                    # default value (next_check_at = now + (24 * 60 * 60)) when status is BUILD,
                                    # because it can happen that in this case the task is never processed
                                    _update_refresh(task["status"])

                    except Exception as e:
                        new_status = "FAILED"
                        db_vim_info_update = {
                            "vim_status": "VIM_ERROR",
                            "vim_message": str(e),
                        }

                        if not isinstance(
                            e, (NsWorkerException, vimconn.VimConnException)
                        ):
                            self.logger.error(
                                "Unexpected exception at _delete_task task={}: {}".format(
                                    task["task_id"], e
                                ),
                                exc_info=True,
                            )

                    try:
                        if db_vim_info_update:
                            db_vim_update = db_vim_info_update.copy()
                            db_ro_task_update.update(
                                {
                                    "vim_info." + k: v
                                    for k, v in db_vim_info_update.items()
                                }
                            )
                            ro_task["vim_info"].update(db_vim_info_update)

                        if new_status:
                            if task_action == "CREATE":
                                task_status_create = new_status
                            db_ro_task_update[task_path] = new_status

                        if target_update or db_vim_update:
                            if target_update == "DELETE":
                                self._update_target(task, None)
                            elif target_update == "COPY_VIM_INFO":
                                self._update_target(task, ro_task["vim_info"])
                            else:
                                self._update_target(task, db_vim_update)

                    except Exception as e:
                        if (
                            isinstance(e, DbException)
                            and e.http_code == HTTPStatus.NOT_FOUND
                        ):
                            # if the vnfrs or nsrs has been removed from database, this task must be removed
                            self.logger.debug(
                                "marking to delete task={}".format(task["task_id"])
                            )
                            self.tasks_to_delete.append(task)
                        else:
                            self.logger.error(
                                "Unexpected exception at _update_target task={}: {}".format(
                                    task["task_id"], e
                                ),
                                exc_info=True,
                            )

            locked_at = ro_task["locked_at"]

            if lock_object:
                locked_at = [
                    lock_object["locked_at"],
                    lock_object["locked_at"] + self.task_locked_time,
                ]
                # locked_at contains two times to avoid race condition. In case the lock has been renewed, it will
                # contain exactly locked_at + self.task_locked_time
                LockRenew.remove_lock_object(lock_object)

            q_filter = {
                "_id": ro_task["_id"],
                "to_check_at": ro_task["to_check_at"],
                "locked_at": locked_at,
            }
            # modify own task. Try filtering by to_next_check. For race condition if to_check_at has been modified,
            # outside this task (by ro_nbi) do not update it
            db_ro_task_update["locked_by"] = None
            # locked_at converted to int only for debugging. When it is not decimals it means it has been unlocked
            db_ro_task_update["locked_at"] = int(now - self.task_locked_time)
            db_ro_task_update["modified_at"] = now
            db_ro_task_update["to_check_at"] = next_check_at

            """
            # Log RO tasks only when loglevel is DEBUG
            if self.logger.getEffectiveLevel() == logging.DEBUG:
                db_ro_task_update_log = db_ro_task_update.copy()
                db_ro_task_update_log["_id"] = q_filter["_id"]
                self._log_ro_task(None, db_ro_task_update_log, None, "TASK_WF", "SET_TASK")
            """

            if not self.db.set_one(
                "ro_tasks",
                update_dict=db_ro_task_update,
                q_filter=q_filter,
                fail_on_empty=False,
            ):
                del db_ro_task_update["to_check_at"]
                del q_filter["to_check_at"]
                """
                # Log RO tasks only when loglevel is DEBUG
                if self.logger.getEffectiveLevel() == logging.DEBUG:
                    self._log_ro_task(
                        None,
                        db_ro_task_update_log,
                        None,
                        "TASK_WF",
                        "SET_TASK " + str(q_filter),
                    )
                """
                self.db.set_one(
                    "ro_tasks",
                    q_filter=q_filter,
                    update_dict=db_ro_task_update,
                    fail_on_empty=True,
                )
        except DbException as e:
            self.logger.error(
                "ro_task={} Error updating database {}".format(ro_task_id, e)
            )
        except Exception as e:
            self.logger.error(
                "Error executing ro_task={}: {}".format(ro_task_id, e), exc_info=True
            )

    def _update_target(self, task, ro_vim_item_update):
        table, _, temp = task["target_record"].partition(":")
        _id, _, path_vim_status = temp.partition(":")
        path_item = path_vim_status[: path_vim_status.rfind(".")]
        path_item = path_item[: path_item.rfind(".")]
        # path_vim_status: dot separated list targeting vim information, e.g. "vdur.10.vim_info.vim:id"
        # path_item: dot separated list targeting record information, e.g. "vdur.10"

        if ro_vim_item_update:
            update_dict = {
                path_vim_status + "." + k: v
                for k, v in ro_vim_item_update.items()
                if k
                in (
                    "vim_id",
                    "vim_details",
                    "vim_message",
                    "vim_name",
                    "vim_status",
                    "interfaces",
                    "interfaces_backup",
                )
            }

            if path_vim_status.startswith("vdur."):
                # for backward compatibility, add vdur.name apart from vdur.vim_name
                if ro_vim_item_update.get("vim_name"):
                    update_dict[path_item + ".name"] = ro_vim_item_update["vim_name"]

                # for backward compatibility, add vdur.vim-id apart from vdur.vim_id
                if ro_vim_item_update.get("vim_id"):
                    update_dict[path_item + ".vim-id"] = ro_vim_item_update["vim_id"]

                # update general status
                if ro_vim_item_update.get("vim_status"):
                    update_dict[path_item + ".status"] = ro_vim_item_update[
                        "vim_status"
                    ]

            if ro_vim_item_update.get("interfaces"):
                path_interfaces = path_item + ".interfaces"

                for i, iface in enumerate(ro_vim_item_update.get("interfaces")):
                    if iface:
                        update_dict.update(
                            {
                                path_interfaces + ".{}.".format(i) + k: v
                                for k, v in iface.items()
                                if k in ("vlan", "compute_node", "pci")
                            }
                        )

                        # put ip_address and mac_address with ip-address and mac-address
                        if iface.get("ip_address"):
                            update_dict[
                                path_interfaces + ".{}.".format(i) + "ip-address"
                            ] = iface["ip_address"]

                        if iface.get("mac_address"):
                            update_dict[
                                path_interfaces + ".{}.".format(i) + "mac-address"
                            ] = iface["mac_address"]

                        if iface.get("mgmt_vnf_interface") and iface.get("ip_address"):
                            update_dict["ip-address"] = iface.get("ip_address").split(
                                ";"
                            )[0]

                        if iface.get("mgmt_vdu_interface") and iface.get("ip_address"):
                            update_dict[path_item + ".ip-address"] = iface.get(
                                "ip_address"
                            ).split(";")[0]

            self.db.set_one(table, q_filter={"_id": _id}, update_dict=update_dict)

            # If interfaces exists, it backups VDU interfaces in the DB for healing operations
            if ro_vim_item_update.get("interfaces"):
                search_key = path_vim_status + ".interfaces"
                if update_dict.get(search_key):
                    interfaces_backup_update = {
                        path_vim_status + ".interfaces_backup": update_dict[search_key]
                    }

                    self.db.set_one(
                        table,
                        q_filter={"_id": _id},
                        update_dict=interfaces_backup_update,
                    )

        else:
            update_dict = {path_item + ".status": "DELETED"}
            self.db.set_one(
                table,
                q_filter={"_id": _id},
                update_dict=update_dict,
                unset={path_vim_status: None},
            )

    def _process_delete_db_tasks(self):
        """
        Delete task from database because vnfrs or nsrs or both have been deleted
        :return: None. Uses and modify self.tasks_to_delete
        """
        while self.tasks_to_delete:
            task = self.tasks_to_delete[0]
            vnfrs_deleted = None
            nsr_id = task["nsr_id"]

            if task["target_record"].startswith("vnfrs:"):
                # check if nsrs is present
                if self.db.get_one("nsrs", {"_id": nsr_id}, fail_on_empty=False):
                    vnfrs_deleted = task["target_record"].split(":")[1]

            try:
                self.delete_db_tasks(self.db, nsr_id, vnfrs_deleted)
            except Exception as e:
                self.logger.error(
                    "Error deleting task={}: {}".format(task["task_id"], e)
                )
            self.tasks_to_delete.pop(0)

    @staticmethod
    def delete_db_tasks(db, nsr_id, vnfrs_deleted):
        """
        Static method because it is called from osm_ng_ro.ns
        :param db: instance of database to use
        :param nsr_id: affected nsrs id
        :param vnfrs_deleted: only tasks with this vnfr id. If None, all affected by nsr_id
        :return: None, exception is fails
        """
        retries = 5
        for retry in range(retries):
            ro_tasks = db.get_list("ro_tasks", {"tasks.nsr_id": nsr_id})
            now = time.time()
            conflict = False

            for ro_task in ro_tasks:
                db_update = {}
                to_delete_ro_task = True

                for index, task in enumerate(ro_task["tasks"]):
                    if not task:
                        pass
                    elif (not vnfrs_deleted and task["nsr_id"] == nsr_id) or (
                        vnfrs_deleted
                        and task["target_record"].startswith("vnfrs:" + vnfrs_deleted)
                    ):
                        db_update["tasks.{}".format(index)] = None
                    else:
                        # used by other nsr, ro_task cannot be deleted
                        to_delete_ro_task = False

                # delete or update if nobody has changed ro_task meanwhile. Used modified_at for known if changed
                if to_delete_ro_task:
                    if not db.del_one(
                        "ro_tasks",
                        q_filter={
                            "_id": ro_task["_id"],
                            "modified_at": ro_task["modified_at"],
                        },
                        fail_on_empty=False,
                    ):
                        conflict = True
                elif db_update:
                    db_update["modified_at"] = now
                    if not db.set_one(
                        "ro_tasks",
                        q_filter={
                            "_id": ro_task["_id"],
                            "modified_at": ro_task["modified_at"],
                        },
                        update_dict=db_update,
                        fail_on_empty=False,
                    ):
                        conflict = True
            if not conflict:
                return
        else:
            raise NsWorkerException("Exceeded {} retries".format(retries))

    def run(self):
        # load database
        self.logger.info("Starting")
        while True:
            # step 1: get commands from queue
            try:
                if self.vim_targets:
                    task = self.task_queue.get(block=False)
                else:
                    if not self.idle:
                        self.logger.debug("enters in idle state")
                    self.idle = True
                    task = self.task_queue.get(block=True)
                    self.idle = False

                if task[0] == "terminate":
                    break
                elif task[0] == "load_vim":
                    self.logger.info("order to load vim {}".format(task[1]))
                    self._load_vim(task[1])
                elif task[0] == "unload_vim":
                    self.logger.info("order to unload vim {}".format(task[1]))
                    self._unload_vim(task[1])
                elif task[0] == "reload_vim":
                    self._reload_vim(task[1])
                elif task[0] == "check_vim":
                    self.logger.info("order to check vim {}".format(task[1]))
                    self._check_vim(task[1])
                continue
            except Exception as e:
                if isinstance(e, queue.Empty):
                    pass
                else:
                    self.logger.critical(
                        "Error processing task: {}".format(e), exc_info=True
                    )

            # step 2: process pending_tasks, delete not needed tasks
            try:
                if self.tasks_to_delete:
                    self._process_delete_db_tasks()
                busy = False
                """
                # Log RO tasks only when loglevel is DEBUG
                if self.logger.getEffectiveLevel() == logging.DEBUG:
                    _ = self._get_db_all_tasks()
                """
                ro_task = self._get_db_task()
                if ro_task:
                    self.logger.debug("Task to process: {}".format(ro_task))
                    time.sleep(1)
                    self._process_pending_tasks(ro_task)
                    busy = True
                if not busy:
                    time.sleep(5)
            except Exception as e:
                self.logger.critical(
                    "Unexpected exception at run: " + str(e), exc_info=True
                )

        self.logger.info("Finishing")
