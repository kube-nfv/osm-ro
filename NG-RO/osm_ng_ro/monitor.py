#######################################################################################
# Copyright ETSI Contributors and Others.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#######################################################################################
from copy import deepcopy
from dataclasses import dataclass
import logging
from os import makedirs, path
from pprint import pformat
import random
import threading
from typing import Optional

from importlib_metadata import entry_points
from osm_common import dbmemory, dbmongo
from osm_common.dbbase import DbException
from osm_ng_ro.ns_thread import ConfigValidate
from osm_ro_plugin import vimconn
import yaml
from yaml.representer import RepresenterError


openStackvmStatusOk = [
    "ACTIVE",
    "PAUSED",
    "SUSPENDED",
    "SHUTOFF",
    "BUILD",
]

openStacknetStatusOk = [
    "ACTIVE",
    "PAUSED",
    "BUILD",
]

db_vim_collection = "vim_accounts"
vim_type = "openstack"
ro_task_collection = "ro_tasks"
plugin_name = "rovim_openstack"
monitoring_task = None


@dataclass
class VmToMonitor:
    vm_id: str
    target_record: str


@dataclass
class VimToMonitor:
    vim_id: str
    vms: list


class MonitorVmsException(Exception):
    def __init__(self, message):
        super(Exception, self).__init__(message)


class MonitorDbException(Exception):
    def __init__(self, message):
        super(Exception, self).__init__(message)


class MonitorVimException(Exception):
    def __init__(self, message):
        super(Exception, self).__init__(message)


class SafeDumper(yaml.SafeDumper):
    def represent_data(self, data):
        if isinstance(data, dict) and data.__class__ != dict:
            # A solution to convert subclasses of dict to dicts which is not handled by pyyaml.
            data = dict(data.items())
        return super(SafeDumper, self).represent_data(data)


class MonitorVms:
    def __init__(self, config: dict):
        self.config = config
        self.db = None
        self.refresh_config = ConfigValidate(config)
        self.my_vims = {}
        self.plugins = {}
        self.logger = logging.getLogger("ro.monitor")
        self.connect_db()
        self.db_vims = self.get_db_vims()
        self.load_vims()

    def load_vims(self) -> None:
        for vim in self.db_vims:
            if vim["_id"] not in self.my_vims:
                self._load_vim(vim["_id"])

    def connect_db(self) -> None:
        """Connect to the Database.

        Raises:
           MonitorDbException
        """
        try:
            if not self.db:
                if self.config["database"]["driver"] == "mongo":
                    self.db = dbmongo.DbMongo()
                    self.db.db_connect(self.config["database"])
                elif self.config["database"]["driver"] == "memory":
                    self.db = dbmemory.DbMemory()
                    self.db.db_connect(self.config["database"])
                else:
                    raise MonitorDbException(
                        "Invalid configuration param '{}' at '[database]':'driver'".format(
                            self.config["database"]["driver"]
                        )
                    )
        except (DbException, MonitorDbException, ValueError) as e:
            raise MonitorDbException(str(e))

    def get_db_vims(self) -> list:
        """Get all VIM accounts which types are Openstack."""
        return self.db.get_list(db_vim_collection, {"vim_type": vim_type})

    def find_ro_tasks_to_monitor(self) -> list:
        """Get the ro_tasks which belongs to vdu and status DONE."""
        return self.db.get_list(
            ro_task_collection,
            q_filter={
                "tasks.status": ["DONE"],
                "tasks.item": ["vdu"],
            },
        )

    @staticmethod
    def _initialize_target_vim(vim_module_conn, vim: dict) -> object:
        """Create the VIM connector object with given vim details.

        Args:
            vim_module_conn (class):    VIM connector class
            vim (dict):                 VIM details to initialize VIM connecter object

        Returns:
            VIM connector   (object):   VIM connector object
        """
        return vim_module_conn(
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

    def _load_vim(self, target_id) -> None:
        """Load or reload a vim_account.
        Read content from database, load the plugin if not loaded, then it fills my_vims dictionary.

        Args:
            target_id   (str):      ID of vim account

        Raises:
            MonitorVimException
        """
        try:
            vim = self.db.get_one(db_vim_collection, {"_id": target_id})
            schema_version = vim.get("schema_version")
            self.db.encrypt_decrypt_fields(
                vim,
                "decrypt",
                fields=("password", "secret"),
                schema_version=schema_version,
                salt=target_id,
            )
            self._process_vim_config(target_id, vim)
            vim_module_conn = self._load_plugin(plugin_name)
            self.my_vims[target_id] = self._initialize_target_vim(vim_module_conn, vim)
            self.logger.debug(
                "Connector loaded for {}, plugin={}".format(target_id, plugin_name)
            )
        except (
            DbException,
            IOError,
            AttributeError,
            MonitorDbException,
            MonitorVimException,
            TypeError,
        ) as e:
            raise MonitorVimException(
                "Cannot load {} plugin={}: {}".format(target_id, plugin_name, str(e))
            )

    @staticmethod
    def _process_vim_config(target_id: str, db_vim: dict) -> None:
        """
        Process vim config, creating vim configuration files as ca_cert
        Args:
            target_id   (str): vim id
            db_vim      (dict): Vim dictionary obtained from database

        Raises:
            MonitorVimException
        """
        if not db_vim.get("config"):
            return
        file_name = ""
        work_dir = "/app/osm_ro/certs"
        try:
            if db_vim["config"].get("ca_cert_content"):
                file_name = f"{work_dir}/{target_id}:{random.randint(0, 99999)}"

                if not path.isdir(file_name):
                    makedirs(file_name)

                file_name = file_name + "/ca_cert"

                with open(file_name, "w") as f:
                    f.write(db_vim["config"]["ca_cert_content"])
                    del db_vim["config"]["ca_cert_content"]
                    db_vim["config"]["ca_cert"] = file_name

        except (FileNotFoundError, IOError, OSError) as e:
            raise MonitorVimException(
                "Error writing to file '{}': {}".format(file_name, e)
            )

    def _load_plugin(self, name: str = "rovim_openstack", type: str = "vim"):
        """Finds the proper VIM connector and returns VIM connector class name.
        Args:
            name  (str):          rovim_openstack
            type  (str):          vim

        Returns:
            VIM connector class name    (class)

        Raises:
            MonitorVimException
        """
        try:
            if name in self.plugins:
                return self.plugins[name]

            for ep in entry_points(group="osm_ro{}.plugins".format(type), name=name):
                self.plugins[name] = ep.load()
                return self.plugins[name]

        except Exception as e:
            raise MonitorVimException("Cannot load plugin osm_{}: {}".format(name, e))

    @staticmethod
    def create_vm_to_monitor(ro_task: dict) -> Optional[object]:
        """Create VM using dataclass with ro task details.

        Args:
            ro_task (dict):             Details of ro_task

        Returns:
            VmToMonitor (object)
        """
        if not ro_task:
            return
        return VmToMonitor(
            ro_task["vim_info"]["vim_id"], ro_task["tasks"][0]["target_record"]
        )

    @staticmethod
    def add_vm_to_existing_vim(
        vims_to_monitor: list, ro_task: dict, target_vim: str
    ) -> bool:
        """Add VmToMonitor to existing VIM list.

        Args:
            vims_to_monitor (list):     List of VIMs to monitor
            ro_task (dict):             ro_task details
            target_vim  (str):          ID of target VIM

        Returns:
            Boolean         If VM is added to VIM list, it returns True else False.
        """
        for vim in vims_to_monitor:
            if target_vim == vim.vim_id:
                vm_to_monitor = MonitorVms.create_vm_to_monitor(ro_task)
                vim.vms.append(vm_to_monitor)
                return True
        return False

    @staticmethod
    def add_new_vim_for_monitoring(
        vims_to_monitor: list, ro_task: dict, target_vim: str
    ) -> None:
        """Create a new VIM object and add to vims_to_monitor list.

        Args:
            vims_to_monitor (list):     List of VIMs to monitor
            ro_task (dict):             ro_task details
            target_vim  (str):          ID of target VIM
        """
        vim_to_monitor = VimToMonitor(target_vim, [])
        vm_to_monitor = MonitorVms.create_vm_to_monitor(ro_task)
        vim_to_monitor.vms.append(vm_to_monitor)
        vims_to_monitor.append(vim_to_monitor)

    @staticmethod
    def prepare_vims_to_monitor(
        vims_to_monitor: list, ro_task: dict, target_vim: str
    ) -> None:
        """If the required VIM exists in the vims_to_monitor list, add VM under related VIM,
        otherwise create a new VIM object and add VM to this new created VIM.

        Args:
            vims_to_monitor (list):     List of VIMs to monitor
            ro_task (dict):             ro_task details
            target_vim  (str):          ID of target VIM
        """
        if not MonitorVms.add_vm_to_existing_vim(vims_to_monitor, ro_task, target_vim):
            MonitorVms.add_new_vim_for_monitoring(vims_to_monitor, ro_task, target_vim)

    def _get_db_paths(self, target_record: str) -> tuple:
        """Get the database paths and info of target VDU and VIM.

        Args:
            target_record   (str):      A string which includes vnfr_id, vdur_id, vim_id

        Returns:
            (vim_info_path: str, vim_id: str, vnfr_id: str, vdur_path:str, vdur_index: int, db_vnfr: dict)  tuple

        Raises:
            MonitorVmsException
        """
        try:
            [_, vnfr_id, vdur_info, vim_id] = target_record.split(":")
            vim_info_path = vdur_info + ":" + vim_id
            vdur_path = vim_info_path.split(".vim_info.")[0]
            vdur_index = int(vdur_path.split(".")[1])
            db_vnfr = self.db.get_one("vnfrs", {"_id": vnfr_id}, fail_on_empty=False)
            return vim_info_path, vim_id, vnfr_id, vdur_path, vdur_index, db_vnfr
        except (DbException, ValueError) as e:
            raise MonitorVmsException(str(e))

    @staticmethod
    def _check_if_vdur_vim_info_exists(
        db_vnfr: dict, vdur_index: int
    ) -> Optional[bool]:
        """Check if VNF record and vdur vim_info record exists.

        Args:
            db_vnfr (dict):             VNF record
            vdur_index  (int):          index of vdur under db_vnfr["vdur"]

        Returns:
            Boolean                     True if VNF record and vdur vim_info record exists.
        """
        try:
            if db_vnfr and db_vnfr.get("vdur") and isinstance(vdur_index, int):
                if db_vnfr["vdur"][vdur_index] and db_vnfr["vdur"][vdur_index].get(
                    "vim_info"
                ):
                    return True
        except IndexError:
            return

    def _get_vm_data_from_db(self, vm_to_monitor: object) -> Optional[tuple]:
        """Get the required DB path and VIM info data from database.

        Args:
            vm_to_monitor   (object):    Includes vm_id and target record in DB.

        Returns:
            (vdur_path: str, vdur_vim_info_update: dict, db_vnfr: dict, existing_vim_info: dict, vnfr_id,vim_info_path: str)    (Tuple):
            Required VM info if _check_if_vdur_vim_info_exists else None
        """
        (
            vim_info_path,
            vim_id,
            vnfr_id,
            vdur_path,
            vdur_index,
            db_vnfr,
        ) = self._get_db_paths(vm_to_monitor.target_record)
        if not self._check_if_vdur_vim_info_exists(db_vnfr, vdur_index):
            return

        existing_vim_info = db_vnfr["vdur"][vdur_index]["vim_info"].get("vim:" + vim_id)
        if not existing_vim_info:
            return

        vdur_vim_info_update = deepcopy(existing_vim_info)
        return (
            vdur_path,
            vdur_vim_info_update,
            db_vnfr,
            existing_vim_info,
            vnfr_id,
            vim_info_path,
        )

    @staticmethod
    def update_vim_info_for_deleted_vm(vdur_vim_info_update: dict) -> None:
        """Updates the vdur_vim_info_update to report that VM is deleted.

        Args:
             vdur_vim_info_update    (dict):     Dictionary to be updated and used to update VDUR later.
        """
        vdur_vim_info_update.update(
            {
                "vim_status": "DELETED",
                "vim_message": "Deleted externally",
                "vim_id": None,
                "vim_name": None,
                "interfaces": None,
            }
        )

    def report_deleted_vdur(self, vm_to_monitor: object) -> None:
        """VM does not exist in the Openstack Cloud so update the VNFR to report VM deletion.

        Args:
            vm_to_monitor   (object):        VM needs to be reported as deleted.
        """
        vm_data = self._get_vm_data_from_db(vm_to_monitor)
        if not vm_data:
            return
        (
            vdur_path,
            vdur_vim_info_update,
            _,
            existing_vim_info,
            vnfr_id,
            vim_info_path,
        ) = vm_data
        self.update_vim_info_for_deleted_vm(vdur_vim_info_update)
        vdur_update = {
            vdur_path + ".status": "DELETED",
        }

        if existing_vim_info != vdur_vim_info_update:
            # VNFR record is updated one time upon VM deletion.
            self.logger.info(f"Reporting deletion of VM: {vm_to_monitor.vm_id}")
            self.backup_vdu_interfaces(vdur_vim_info_update)
            all_updates = [vdur_update, {vim_info_path: vdur_vim_info_update}]
            self.update_in_database(all_updates, vnfr_id)
            self.logger.info(f"Updated vnfr for vm_id: {vm_to_monitor.vm_id}.")

    def update_vnfrs(self, servers: list, ports: dict, vms_to_monitor: list) -> None:
        """Update the VDURs according to the latest information provided by servers list.

        Args:
            servers    (list):          List of existing VMs comes from single Openstack VIM account
            ports     (dict):           List of all ports comes from single Openstack VIM account
            vms_to_monitor  (list):     List of VMs to be monitored and updated.
        """
        for vm_to_monitor in vms_to_monitor:
            server = next(
                filter(lambda server: server.id == vm_to_monitor.vm_id, servers), None
            )
            if server:
                self.report_vdur_updates(server, vm_to_monitor, ports)
            else:
                self.report_deleted_vdur(vm_to_monitor)

    def serialize(self, value: dict) -> Optional[str]:
        """Serialization of python basic types.
        In the case value is not serializable a message will be logged.

        Args:
            value   (dict/str):     Data to serialize

        Returns:
            serialized_value    (str, yaml)
        """
        if isinstance(value, str):
            return value
        try:
            return yaml.dump(
                value, Dumper=SafeDumper, default_flow_style=True, width=256
            )
        except RepresenterError:
            self.logger.info(
                "The following entity cannot be serialized in YAML:\n\n%s\n\n",
                pformat(value),
                exc_info=True,
            )
            return str(value)

    def _get_server_info(self, server: object) -> str:
        """Get the server info, extract some fields and returns info as string.

        Args:
            server  (object):        VM info object

        Returns:
            server_info (string)
        """
        server_info = server.to_dict()
        server_info.pop("OS-EXT-SRV-ATTR:user_data", None)
        server_info.pop("user_data", None)
        return self.serialize(server_info)

    def check_vm_status_updates(
        self,
        vdur_vim_info_update: dict,
        vdur_update: dict,
        server: object,
        vdur_path: str,
    ) -> None:
        """Fills up dictionaries to update VDUR according to server.status.

        Args:
            vdur_vim_info_update    (dict):         Dictionary which keeps the differences of vdur_vim_info
            vdur_update             (dict):         Dictionary which keeps the differences of vdur
            server                  (server):       VM info
            vdur_path               (str):          Path of VDUR in DB
        """
        if server.status in openStackvmStatusOk:
            vdur_vim_info_update["vim_status"] = vdur_update[vdur_path + ".status"] = (
                server.status
            )

        else:
            vdur_vim_info_update["vim_status"] = vdur_update[vdur_path + ".status"] = (
                server.status
            )
            vdur_vim_info_update["vim_message"] = "VIM status reported " + server.status

        vdur_vim_info_update["vim_details"] = self._get_server_info(server)
        vdur_vim_info_update["vim_id"] = server.id
        vdur_vim_info_update["vim_name"] = vdur_update[vdur_path + ".name"] = (
            server.name
        )

    @staticmethod
    def get_interface_info(
        ports: dict, interface: dict, server: object
    ) -> Optional[dict]:
        """Get the updated port info regarding with existing interface of server.

        Args:
            ports       (dict):             List of all ports belong to single VIM account
            interface   (dict):             Existing interface info which is taken from DB
            server  (object):               Server info

        Returns:
            port    (dict):                 The updated port info related to existing interface of server
        """
        return next(
            filter(
                lambda port: port.get("id") == interface.get("vim_interface_id")
                and port.get("device_id") == server.id,
                ports["ports"],
            ),
            None,
        )

    @staticmethod
    def check_vlan_pci_updates(
        interface_info: dict, index: int, vdur_vim_info_update: dict
    ) -> None:
        """If interface has pci and vlan, update vdur_vim_info dictionary with the refreshed data.

        Args:
            interface_info          (dict):     Refreshed interface info
            index                   (int):      Index of interface in VDUR
            vdur_vim_info_update    (dict):     Dictionary to be updated and used to update VDUR later.
        """
        if interface_info.get("binding:profile") and interface_info[
            "binding:profile"
        ].get("pci_slot"):
            pci = interface_info["binding:profile"]["pci_slot"]
            vdur_vim_info_update["interfaces"][index]["pci"] = pci

        if interface_info.get("binding:vif_details"):
            vdur_vim_info_update["interfaces"][index]["vlan"] = interface_info[
                "binding:vif_details"
            ].get("vlan")

    @staticmethod
    def check_vdur_interface_updates(
        vdur_update: dict,
        vdur_path: str,
        index: int,
        interface_info: dict,
        old_interface: dict,
        vnfr_update: dict,
        vnfr_id: str,
    ) -> None:
        """Updates the vdur_update dictionary which stores differences between the latest interface data and data in DB.

        Args:
            vdur_update     (dict):         Dictionary used to store vdur updates
            vdur_path       (str):          VDUR record path in DB
            index           (int):          Index of interface in VDUR
            interface_info  (dict):         Refreshed interface info
            old_interface       (dict):     The previous interface info comes from DB
            vnfr_update     (dict):         VDUR record path in DB
            vnfr_id         (str):          VNFR ID
        """
        current_ip_address = MonitorVms._get_current_ip_address(interface_info)
        if current_ip_address:
            vdur_update[vdur_path + ".interfaces." + str(index) + ".ip-address"] = (
                current_ip_address
            )

            if old_interface.get("mgmt_vdu_interface"):
                vdur_update[vdur_path + ".ip-address"] = current_ip_address

            if old_interface.get("mgmt_vnf_interface"):
                vnfr_update[vnfr_id + ".ip-address"] = current_ip_address

        vdur_update[vdur_path + ".interfaces." + str(index) + ".mac-address"] = (
            interface_info.get("mac_address")
        )

    @staticmethod
    def _get_dual_ip(data=None):
        if data:
            ip_addresses = [item["ip_address"] for item in data]
            return ";".join(ip_addresses) if len(ip_addresses) > 1 else ip_addresses[0]
        else:
            return None

    @staticmethod
    def _get_current_ip_address(interface_info: dict) -> Optional[str]:
        if interface_info.get("fixed_ips") and interface_info["fixed_ips"][0]:
            return MonitorVms._get_dual_ip(interface_info.get("fixed_ips"))

    @staticmethod
    def backup_vdu_interfaces(vdur_vim_info_update: dict) -> None:
        """Backup VDU interfaces as interfaces_backup.

        Args:
            vdur_vim_info_update    (dict):   Dictionary used to store vdur_vim_info updates
        """
        if vdur_vim_info_update.get("interfaces") and not vdur_vim_info_update.get(
            "vim_message"
        ):
            vdur_vim_info_update["interfaces_backup"] = vdur_vim_info_update[
                "interfaces"
            ]

    def update_vdur_vim_info_interfaces(
        self,
        vdur_vim_info_update: dict,
        index: int,
        interface_info: dict,
        server: object,
    ) -> None:
        """Update the vdur_vim_info dictionary with the latest interface info.

        Args:
            vdur_vim_info_update    (dict):     The dictionary which is used to store vdur_vim_info updates
            index       (int):                  Interface index
            interface_info  (dict):             The latest interface info
            server  (object):                The latest VM info
        """
        if not (
            vdur_vim_info_update.get("interfaces")
            and vdur_vim_info_update["interfaces"][index]
        ):
            raise MonitorVmsException("Existing interfaces info could not found.")

        vdur_vim_info_update["interfaces"][index].update(
            {
                "mac_address": interface_info["mac_address"],
                "ip_address": (
                    interface_info["fixed_ips"][0].get("ip_address")
                    if interface_info.get("fixed_ips")
                    else None
                ),
                "vim_net_id": interface_info["network_id"],
                "vim_info": self.serialize(interface_info),
                "compute_node": (
                    server.to_dict()["OS-EXT-SRV-ATTR:host"]
                    if server.to_dict().get("OS-EXT-SRV-ATTR:host")
                    else None
                ),
            }
        )

    def prepare_interface_updates(
        self,
        vdur_vim_info_update: dict,
        index: int,
        interface_info: dict,
        server: object,
        vdur_path: str,
        vnfr_update: dict,
        old_interface: dict,
        vdur_update: dict,
        vnfr_id: str,
    ) -> None:
        """Updates network related info in vdur_vim_info and vdur by using the latest interface info.

        Args:
            vdur_vim_info_update    (dict):     Dictionary used to store vdur_vim_info updates
            index       (int):                  Interface index
            interface_info  (dict):             The latest interface info
            server  (object):                   The latest VM info
            vdur_path       (str):              VDUR record path in DB
            vnfr_update     (dict):             VDUR record path in DB
            old_interface  (dict):              The previous interface info comes from DB
            vdur_update     (dict):             Dictionary used to store vdur updates
            vnfr_id         (str):              VNFR ID
        """
        self.update_vdur_vim_info_interfaces(
            vdur_vim_info_update, index, interface_info, server
        )
        self.check_vlan_pci_updates(interface_info, index, vdur_vim_info_update)
        self.check_vdur_interface_updates(
            vdur_update,
            vdur_path,
            index,
            interface_info,
            old_interface,
            vnfr_update,
            vnfr_id,
        )

    def check_vm_interface_updates(
        self,
        server: object,
        existing_vim_info: dict,
        ports: dict,
        vdur_vim_info_update: dict,
        vdur_update: dict,
        vdur_path: str,
        vnfr_update: dict,
        vnfr_id: str,
    ) -> None:
        """Gets the refreshed interfaces info of server and updates the VDUR if interfaces exist,
        otherwise reports that interfaces are deleted.

        Args:
            server  (object):                   The latest VM info
            existing_vim_info   (dict):         VM info details comes from DB
            ports       (dict):                 All ports info belongs to single VIM account
            vdur_vim_info_update    (dict):     Dictionary used to store vdur_vim_info updates
            vdur_update     (dict):             Dictionary used to store vdur updates
            vdur_path       (str):              VDUR record path in DB
            vnfr_update     (dict):             VDUR record path in DB
            vnfr_id         (str):              VNFR ID
        """
        for index, old_interface in enumerate(existing_vim_info["interfaces"]):
            interface_info = self.get_interface_info(ports, old_interface, server)
            if not interface_info:
                vdur_vim_info_update["vim_message"] = (
                    f"Interface {old_interface['vim_interface_id']} deleted externally."
                )

            else:
                if interface_info.get("status") in openStacknetStatusOk:
                    self.prepare_interface_updates(
                        vdur_vim_info_update,
                        index,
                        interface_info,
                        server,
                        vdur_path,
                        vnfr_update,
                        old_interface,
                        vdur_update,
                        vnfr_id,
                    )

                else:
                    vdur_vim_info_update["vim_message"] = (
                        f"Interface {old_interface['vim_interface_id']} status: "
                        + interface_info.get("status")
                    )

    def update_in_database(self, all_updates: list, vnfr_id: str) -> None:
        """Update differences in VNFR.

        Args:
            all_updates     (list):     List of dictionaries which includes differences
            vnfr_id         (str):      VNF record ID

        Raises:
            MonitorDbException
        """
        try:
            for updated_dict in all_updates:
                if updated_dict:
                    self.db.set_list(
                        "vnfrs",
                        update_dict=updated_dict,
                        q_filter={"_id": vnfr_id},
                    )
        except DbException as e:
            raise MonitorDbException(
                f"Error while updating differences in VNFR {str(e)}"
            )

    def report_vdur_updates(
        self, server: object, vm_to_monitor: object, ports: dict
    ) -> None:
        """Report VDU updates by changing the VDUR records in DB.

        Args:
            server      (object):               Refreshed VM info
            vm_to_monitor   (object):           VM to be monitored
            ports       (dict):                 Ports dict includes all ports details regarding with single VIM account
        """
        vm_data = self._get_vm_data_from_db(vm_to_monitor)
        if not vm_data:
            return
        (
            vdur_path,
            vdur_vim_info_update,
            _,
            existing_vim_info,
            vnfr_id,
            vim_info_path,
        ) = vm_data
        vdur_update, vnfr_update = {}, {}

        self.check_vm_status_updates(
            vdur_vim_info_update, vdur_update, server, vdur_path
        )

        self.check_vm_interface_updates(
            server,
            existing_vim_info,
            ports,
            vdur_vim_info_update,
            vdur_update,
            vdur_path,
            vnfr_update,
            vnfr_id,
        )
        # Update vnfr in MongoDB if there are differences
        if existing_vim_info != vdur_vim_info_update:
            self.logger.info(f"Reporting status updates of VM: {vm_to_monitor.vm_id}.")
            self.backup_vdu_interfaces(vdur_vim_info_update)
            all_updates = [
                vdur_update,
                {vim_info_path: vdur_vim_info_update},
                vnfr_update,
            ]
            self.update_in_database(all_updates, vnfr_id)
            self.logger.info(f"Updated vnfr for vm_id: {server.id}.")

    def run(self) -> None:
        """Perfoms the periodic updates of Openstack VMs by sending only two requests to Openstack APIs
        for each VIM account (in order to get details of all servers, all ports).

        Raises:
            MonitorVmsException
        """
        try:
            # If there is not any Openstack type VIM account in DB or VM status updates are disabled by config,
            # Openstack VMs will not be monitored.
            if not self.db_vims or self.refresh_config.active == -1:
                return

            ro_tasks_to_monitor = self.find_ro_tasks_to_monitor()
            db_vims = [vim["_id"] for vim in self.db_vims]
            vims_to_monitor = []

            for ro_task in ro_tasks_to_monitor:
                _, _, target_vim = ro_task["target_id"].partition(":")
                if target_vim in db_vims:
                    self.prepare_vims_to_monitor(vims_to_monitor, ro_task, target_vim)

            for vim in vims_to_monitor:
                try:
                    all_servers, all_ports = self.my_vims[
                        vim.vim_id
                    ].get_monitoring_data()
                    self.update_vnfrs(all_servers, all_ports, vim.vms)
                except (DbException, MonitorDbException) as e:
                    raise MonitorVmsException(str(e))
                except Exception as e:
                    self.logger.info("Exception in vim monitoring {}".format(e))
                    continue
        except (
            DbException,
            MonitorDbException,
            MonitorVimException,
            MonitorVmsException,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            vimconn.VimConnException,
        ) as e:
            raise MonitorVmsException(
                f"Exception while monitoring Openstack VMs: {str(e)}"
            )
        except Exception as e:
            self.logger.info("Exception in monitoring {}".format(e))


def start_monitoring(config: dict):
    global monitoring_task
    if not (config and config.get("period")):
        raise MonitorVmsException("Wrong configuration format is provided.")
    instance = MonitorVms(config)
    period = instance.refresh_config.active
    instance.run()
    if period == -1:
        period = 10 * 24 * 60 * 60  # 10 days (big enough)
    monitoring_task = threading.Timer(period, start_monitoring, args=(config,))
    monitoring_task.start()


def stop_monitoring():
    global monitoring_task
    if monitoring_task:
        monitoring_task.cancel()
