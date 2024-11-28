# -*- coding: utf-8 -*-

##
# Copyright 2015 Telefonica Investigacion y Desarrollo, S.A.U.
# This file is part of openmano
# All Rights Reserved.
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
##

"""
osconnector implements all the methods to interact with openstack using the python-neutronclient.

For the VNF forwarding graph, The OpenStack VIM connector calls the
networking-sfc Neutron extension methods, whose resources are mapped
to the VIM connector's SFC resources as follows:
- Classification (OSM) -> Flow Classifier (Neutron)
- Service Function Instance (OSM) -> Port Pair (Neutron)
- Service Function (OSM) -> Port Pair Group (Neutron)
- Service Function Path (OSM) -> Port Chain (Neutron)
"""

import copy
from http.client import HTTPException
import json
import logging
from pprint import pformat
import random
import re
import time
from typing import Dict, List, Optional, Tuple

from cinderclient import client as cClient
import cinderclient.exceptions as cExceptions
from glanceclient import client as glClient
import glanceclient.exc as gl1Exceptions
from keystoneauth1 import session
from keystoneauth1.identity import v2, v3
import keystoneclient.exceptions as ksExceptions
import keystoneclient.v2_0.client as ksClient_v2
import keystoneclient.v3.client as ksClient_v3
import netaddr
from neutronclient.common import exceptions as neExceptions
from neutronclient.neutron import client as neClient
from novaclient import client as nClient, exceptions as nvExceptions
from osm_ro_plugin import vimconn
from requests.exceptions import ConnectionError
import yaml

__author__ = "Alfonso Tierno, Gerardo Garcia, Pablo Montes, xFlow Research, Igor D.C., Eduardo Sousa"
__date__ = "$22-sep-2017 23:59:59$"

"""contain the openstack virtual machine status to openmano status"""
vmStatus2manoFormat = {
    "ACTIVE": "ACTIVE",
    "PAUSED": "PAUSED",
    "SUSPENDED": "SUSPENDED",
    "SHUTOFF": "INACTIVE",
    "BUILD": "BUILD",
    "ERROR": "ERROR",
    "DELETED": "DELETED",
}
netStatus2manoFormat = {
    "ACTIVE": "ACTIVE",
    "PAUSED": "PAUSED",
    "INACTIVE": "INACTIVE",
    "BUILD": "BUILD",
    "ERROR": "ERROR",
    "DELETED": "DELETED",
}

supportedClassificationTypes = ["legacy_flow_classifier"]

# global var to have a timeout creating and deleting volumes
volume_timeout = 1800
server_timeout = 1800


def catch_any_exception(func):
    def format_exception(*args, **kwargs):
        try:
            return func(*args, *kwargs)
        except Exception as e:
            vimconnector._format_exception(e)

    return format_exception


class SafeDumper(yaml.SafeDumper):
    def represent_data(self, data):
        # Openstack APIs use custom subclasses of dict and YAML safe dumper
        # is designed to not handle that (reference issue 142 of pyyaml)
        if isinstance(data, dict) and data.__class__ != dict:
            # A simple solution is to convert those items back to dicts
            data = dict(data.items())

        return super(SafeDumper, self).represent_data(data)


class vimconnector(vimconn.VimConnector):
    def __init__(
        self,
        uuid,
        name,
        tenant_id,
        tenant_name,
        url,
        url_admin=None,
        user=None,
        passwd=None,
        log_level=None,
        config={},
        persistent_info={},
    ):
        """using common constructor parameters. In this case
        'url' is the keystone authorization url,
        'url_admin' is not use
        """
        api_version = config.get("APIversion")

        if api_version and api_version not in ("v3.3", "v2.0", "2", "3"):
            raise vimconn.VimConnException(
                "Invalid value '{}' for config:APIversion. "
                "Allowed values are 'v3.3', 'v2.0', '2' or '3'".format(api_version)
            )

        vim_type = config.get("vim_type")

        if vim_type and vim_type not in ("vio", "VIO"):
            raise vimconn.VimConnException(
                "Invalid value '{}' for config:vim_type."
                "Allowed values are 'vio' or 'VIO'".format(vim_type)
            )

        if config.get("dataplane_net_vlan_range") is not None:
            # validate vlan ranges provided by user
            self._validate_vlan_ranges(
                config.get("dataplane_net_vlan_range"), "dataplane_net_vlan_range"
            )

        if config.get("multisegment_vlan_range") is not None:
            # validate vlan ranges provided by user
            self._validate_vlan_ranges(
                config.get("multisegment_vlan_range"), "multisegment_vlan_range"
            )

        vimconn.VimConnector.__init__(
            self,
            uuid,
            name,
            tenant_id,
            tenant_name,
            url,
            url_admin,
            user,
            passwd,
            log_level,
            config,
        )

        if self.config.get("insecure") and self.config.get("ca_cert"):
            raise vimconn.VimConnException(
                "options insecure and ca_cert are mutually exclusive"
            )

        self.verify = True

        if self.config.get("insecure"):
            self.verify = False

        if self.config.get("ca_cert"):
            self.verify = self.config.get("ca_cert")

        if not url:
            raise TypeError("url param can not be NoneType")

        self.persistent_info = persistent_info
        self.availability_zone = persistent_info.get("availability_zone", None)
        self.storage_availability_zone = None
        self.vm_av_zone = None
        self.session = persistent_info.get("session", {"reload_client": True})
        self.my_tenant_id = self.session.get("my_tenant_id")
        self.nova = self.session.get("nova")
        self.neutron = self.session.get("neutron")
        self.cinder = self.session.get("cinder")
        self.glance = self.session.get("glance")
        # self.glancev1 = self.session.get("glancev1")
        self.keystone = self.session.get("keystone")
        self.api_version3 = self.session.get("api_version3")
        self.vim_type = self.config.get("vim_type")

        if self.vim_type:
            self.vim_type = self.vim_type.upper()

        if self.config.get("use_internal_endpoint"):
            self.endpoint_type = "internalURL"
        else:
            self.endpoint_type = None

        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("keystoneauth").setLevel(logging.WARNING)
        logging.getLogger("novaclient").setLevel(logging.WARNING)
        self.logger = logging.getLogger("ro.vim.openstack")

        # allow security_groups to be a list or a single string
        if isinstance(self.config.get("security_groups"), str):
            self.config["security_groups"] = [self.config["security_groups"]]

        self.security_groups_id = None

        # ###### VIO Specific Changes #########
        if self.vim_type == "VIO":
            self.logger = logging.getLogger("ro.vim.vio")

        if log_level:
            self.logger.setLevel(getattr(logging, log_level))

    def __getitem__(self, index):
        """Get individuals parameters.
        Throw KeyError"""
        if index == "project_domain_id":
            return self.config.get("project_domain_id")
        elif index == "user_domain_id":
            return self.config.get("user_domain_id")
        else:
            return vimconn.VimConnector.__getitem__(self, index)

    def __setitem__(self, index, value):
        """Set individuals parameters and it is marked as dirty so to force connection reload.
        Throw KeyError"""
        if index == "project_domain_id":
            self.config["project_domain_id"] = value
        elif index == "user_domain_id":
            self.config["user_domain_id"] = value
        else:
            vimconn.VimConnector.__setitem__(self, index, value)

        self.session["reload_client"] = True

    def serialize(self, value):
        """Serialization of python basic types.

        In the case value is not serializable a message will be logged and a
        simple representation of the data that cannot be converted back to
        python is returned.
        """
        if isinstance(value, str):
            return value

        try:
            return yaml.dump(
                value, Dumper=SafeDumper, default_flow_style=True, width=256
            )
        except yaml.representer.RepresenterError:
            self.logger.debug(
                "The following entity cannot be serialized in YAML:\n\n%s\n\n",
                pformat(value),
                exc_info=True,
            )

            return str(value)

    def _reload_connection(self):
        """Called before any operation, it check if credentials has changed
        Throw keystoneclient.apiclient.exceptions.AuthorizationFailure
        """
        # TODO control the timing and possible token timeout, but it seams that python client does this task for us :-)
        if self.session["reload_client"]:
            if self.config.get("APIversion"):
                self.api_version3 = (
                    self.config["APIversion"] == "v3.3"
                    or self.config["APIversion"] == "3"
                )
            else:  # get from ending auth_url that end with v3 or with v2.0
                self.api_version3 = self.url.endswith("/v3") or self.url.endswith(
                    "/v3/"
                )

            self.session["api_version3"] = self.api_version3

            if self.api_version3:
                if self.config.get("project_domain_id") or self.config.get(
                    "project_domain_name"
                ):
                    project_domain_id_default = None
                else:
                    project_domain_id_default = "default"

                if self.config.get("user_domain_id") or self.config.get(
                    "user_domain_name"
                ):
                    user_domain_id_default = None
                else:
                    user_domain_id_default = "default"
                auth = v3.Password(
                    auth_url=self.url,
                    username=self.user,
                    password=self.passwd,
                    project_name=self.tenant_name,
                    project_id=self.tenant_id,
                    project_domain_id=self.config.get(
                        "project_domain_id", project_domain_id_default
                    ),
                    user_domain_id=self.config.get(
                        "user_domain_id", user_domain_id_default
                    ),
                    project_domain_name=self.config.get("project_domain_name"),
                    user_domain_name=self.config.get("user_domain_name"),
                )
            else:
                auth = v2.Password(
                    auth_url=self.url,
                    username=self.user,
                    password=self.passwd,
                    tenant_name=self.tenant_name,
                    tenant_id=self.tenant_id,
                )

            sess = session.Session(auth=auth, verify=self.verify)
            # added region_name to keystone, nova, neutron and cinder to support distributed cloud for Wind River
            # Titanium cloud and StarlingX
            region_name = self.config.get("region_name")

            if self.api_version3:
                self.logger.debug(f"Using Keystone client v3 for VIM {self.id}")
                self.keystone = ksClient_v3.Client(
                    session=sess,
                    endpoint_type=self.endpoint_type,
                    region_name=region_name,
                )
            else:
                self.logger.debug(f"Using Keystone client v2 for VIM {self.id}")
                self.keystone = ksClient_v2.Client(
                    session=sess, endpoint_type=self.endpoint_type
                )

            self.session["keystone"] = self.keystone
            # In order to enable microversion functionality an explicit microversion must be specified in "config".
            # This implementation approach is due to the warning message in
            # https://developer.openstack.org/api-guide/compute/microversions.html
            # where it is stated that microversion backwards compatibility is not guaranteed and clients should
            # always require an specific microversion.
            # To be able to use "device role tagging" functionality define "microversion: 2.32" in datacenter config
            version = self.config.get("microversion")

            if not version:
                version = "2.60"

            # addedd region_name to keystone, nova, neutron and cinder to support distributed cloud for Wind River
            # Titanium cloud and StarlingX
            self.nova = self.session["nova"] = nClient.Client(
                str(version),
                session=sess,
                endpoint_type=self.endpoint_type,
                region_name=region_name,
            )
            self.neutron = self.session["neutron"] = neClient.Client(
                "2.0",
                session=sess,
                endpoint_type=self.endpoint_type,
                region_name=region_name,
            )

            if sess.get_all_version_data(service_type="volumev3"):
                self.logger.debug(f"Using Cinder client v3 for VIM {self.id}")
                self.cinder = self.session["cinder"] = cClient.Client(
                    3,
                    session=sess,
                    endpoint_type=self.endpoint_type,
                    region_name=region_name,
                )
            elif sess.get_all_version_data(service_type="volumev2"):
                self.logger.debug(
                    f"Service type volumev3 not found. Using Cinder client v2 for VIM {self.id}"
                )
                self.cinder = self.session["cinder"] = cClient.Client(
                    2,
                    session=sess,
                    endpoint_type=self.endpoint_type,
                    region_name=region_name,
                )
            else:
                self.logger.debug(
                    f"Service type not found. Using Cinder client v3 for VIM {self.id}"
                )
                self.cinder = self.session["cinder"] = cClient.Client(
                    3,
                    session=sess,
                    endpoint_type=self.endpoint_type,
                    region_name=region_name,
                )

            try:
                self.my_tenant_id = self.session["my_tenant_id"] = sess.get_project_id()
            except Exception:
                self.logger.error("Cannot get project_id from session", exc_info=True)

            if self.endpoint_type == "internalURL":
                glance_service_id = self.keystone.services.list(name="glance")[0].id
                glance_endpoint = self.keystone.endpoints.list(
                    glance_service_id, interface="internal"
                )[0].url
            else:
                glance_endpoint = None

            self.glance = self.session["glance"] = glClient.Client(
                2, session=sess, endpoint=glance_endpoint
            )
            # using version 1 of glance client in new_image()
            # self.glancev1 = self.session["glancev1"] = glClient.Client("1", session=sess,
            #                                                            endpoint=glance_endpoint)
            self.session["reload_client"] = False
            self.persistent_info["session"] = self.session
            # add availablity zone info inside  self.persistent_info
            self._set_availablity_zones()
            self.persistent_info["availability_zone"] = self.availability_zone
            # force to get again security_groups_ids next time they are needed
            self.security_groups_id = None

    def __net_os2mano(self, net_list_dict):
        """Transform the net openstack format to mano format
        net_list_dict can be a list of dict or a single dict"""
        if type(net_list_dict) is dict:
            net_list_ = (net_list_dict,)
        elif type(net_list_dict) is list:
            net_list_ = net_list_dict
        else:
            raise TypeError("param net_list_dict must be a list or a dictionary")
        for net in net_list_:
            if net.get("provider:network_type") == "vlan":
                net["type"] = "data"
            else:
                net["type"] = "bridge"

    def __classification_os2mano(self, class_list_dict):
        """Transform the openstack format (Flow Classifier) to mano format
        (Classification) class_list_dict can be a list of dict or a single dict
        """
        if isinstance(class_list_dict, dict):
            class_list_ = [class_list_dict]
        elif isinstance(class_list_dict, list):
            class_list_ = class_list_dict
        else:
            raise TypeError("param class_list_dict must be a list or a dictionary")
        for classification in class_list_:
            id = classification.pop("id")
            name = classification.pop("name")
            description = classification.pop("description")
            project_id = classification.pop("project_id")
            tenant_id = classification.pop("tenant_id")
            original_classification = copy.deepcopy(classification)
            classification.clear()
            classification["ctype"] = "legacy_flow_classifier"
            classification["definition"] = original_classification
            classification["id"] = id
            classification["name"] = name
            classification["description"] = description
            classification["project_id"] = project_id
            classification["tenant_id"] = tenant_id

    def __sfi_os2mano(self, sfi_list_dict):
        """Transform the openstack format (Port Pair) to mano format (SFI)
        sfi_list_dict can be a list of dict or a single dict
        """
        if isinstance(sfi_list_dict, dict):
            sfi_list_ = [sfi_list_dict]
        elif isinstance(sfi_list_dict, list):
            sfi_list_ = sfi_list_dict
        else:
            raise TypeError("param sfi_list_dict must be a list or a dictionary")

        for sfi in sfi_list_:
            sfi["ingress_ports"] = []
            sfi["egress_ports"] = []

            if sfi.get("ingress"):
                sfi["ingress_ports"].append(sfi["ingress"])

            if sfi.get("egress"):
                sfi["egress_ports"].append(sfi["egress"])

            del sfi["ingress"]
            del sfi["egress"]
            params = sfi.get("service_function_parameters")
            sfc_encap = False

            if params:
                correlation = params.get("correlation")

                if correlation:
                    sfc_encap = True

            sfi["sfc_encap"] = sfc_encap
            del sfi["service_function_parameters"]

    def __sf_os2mano(self, sf_list_dict):
        """Transform the openstack format (Port Pair Group) to mano format (SF)
        sf_list_dict can be a list of dict or a single dict
        """
        if isinstance(sf_list_dict, dict):
            sf_list_ = [sf_list_dict]
        elif isinstance(sf_list_dict, list):
            sf_list_ = sf_list_dict
        else:
            raise TypeError("param sf_list_dict must be a list or a dictionary")

        for sf in sf_list_:
            del sf["port_pair_group_parameters"]
            sf["sfis"] = sf["port_pairs"]
            del sf["port_pairs"]

    def __sfp_os2mano(self, sfp_list_dict):
        """Transform the openstack format (Port Chain) to mano format (SFP)
        sfp_list_dict can be a list of dict or a single dict
        """
        if isinstance(sfp_list_dict, dict):
            sfp_list_ = [sfp_list_dict]
        elif isinstance(sfp_list_dict, list):
            sfp_list_ = sfp_list_dict
        else:
            raise TypeError("param sfp_list_dict must be a list or a dictionary")

        for sfp in sfp_list_:
            params = sfp.pop("chain_parameters")
            sfc_encap = False

            if params:
                correlation = params.get("correlation")

                if correlation:
                    sfc_encap = True

            sfp["sfc_encap"] = sfc_encap
            sfp["spi"] = sfp.pop("chain_id")
            sfp["classifications"] = sfp.pop("flow_classifiers")
            sfp["service_functions"] = sfp.pop("port_pair_groups")

    # placeholder for now; read TODO note below
    def _validate_classification(self, type, definition):
        # only legacy_flow_classifier Type is supported at this point
        return True
        # TODO(igordcard): this method should be an abstract method of an
        # abstract Classification class to be implemented by the specific
        # Types. Also, abstract vimconnector should call the validation
        # method before the implemented VIM connectors are called.

    @staticmethod
    def _format_exception(exception):
        """Transform a keystone, nova, neutron  exception into a vimconn exception discovering the cause"""
        message_error = str(exception)
        tip = ""

        if isinstance(
            exception,
            (
                neExceptions.NetworkNotFoundClient,
                nvExceptions.NotFound,
                nvExceptions.ResourceNotFound,
                ksExceptions.NotFound,
                gl1Exceptions.HTTPNotFound,
                cExceptions.NotFound,
            ),
        ):
            raise vimconn.VimConnNotFoundException(
                type(exception).__name__ + ": " + message_error
            )
        elif isinstance(
            exception,
            (
                HTTPException,
                gl1Exceptions.HTTPException,
                gl1Exceptions.CommunicationError,
                ConnectionError,
                ksExceptions.ConnectionError,
                neExceptions.ConnectionFailed,
                cExceptions.ConnectionError,
            ),
        ):
            if type(exception).__name__ == "SSLError":
                tip = " (maybe option 'insecure' must be added to the VIM)"

            raise vimconn.VimConnConnectionException(
                "Invalid URL or credentials{}: {}".format(tip, message_error)
            )
        elif isinstance(
            exception,
            (
                KeyError,
                nvExceptions.BadRequest,
                ksExceptions.BadRequest,
                gl1Exceptions.BadRequest,
                cExceptions.BadRequest,
            ),
        ):
            if message_error == "OS-EXT-SRV-ATTR:host":
                tip = " (If the user does not have non-admin credentials, this attribute will be missing)"
                raise vimconn.VimConnInsufficientCredentials(
                    type(exception).__name__ + ": " + message_error + tip
                )
            raise vimconn.VimConnException(
                type(exception).__name__ + ": " + message_error
            )

        elif isinstance(
            exception,
            (
                nvExceptions.ClientException,
                ksExceptions.ClientException,
                neExceptions.NeutronException,
                cExceptions.ClientException,
            ),
        ):
            raise vimconn.VimConnUnexpectedResponse(
                type(exception).__name__ + ": " + message_error
            )
        elif isinstance(exception, nvExceptions.Conflict):
            raise vimconn.VimConnConflictException(
                type(exception).__name__ + ": " + message_error
            )
        elif isinstance(exception, vimconn.VimConnException):
            raise exception
        else:  # ()
            logger = logging.getLogger("ro.vim.openstack")
            logger.error("General Exception " + message_error, exc_info=True)

            raise vimconn.VimConnException(
                type(exception).__name__ + ": " + message_error
            )

    def _get_ids_from_name(self, security_group_name=None):
        """
         Obtain ids from name of tenant and security_groups. Store at self .security_groups_id"
        :return: None
        """
        # get tenant_id if only tenant_name is supplied
        self._reload_connection()

        if not self.my_tenant_id:
            raise vimconn.VimConnConnectionException(
                "Error getting tenant information from name={} id={}".format(
                    self.tenant_name, self.tenant_id
                )
            )

        neutron_sg_list = self.neutron.list_security_groups(
            tenant_id=self.my_tenant_id
        )["security_groups"]

        if self.config.get("security_groups") and not self.security_groups_id:
            # convert from name to id
            # neutron_sg_list = self.neutron.list_security_groups(
            #     tenant_id=self.my_tenant_id
            # )["security_groups"]

            self.security_groups_id = []
            for sg in self.config.get("security_groups"):
                for neutron_sg in neutron_sg_list:
                    if sg in (neutron_sg["id"], neutron_sg["name"]):
                        self.security_groups_id.append(neutron_sg["id"])
                        break
                else:
                    self.security_groups_id = None

                    raise vimconn.VimConnConnectionException(
                        "Not found security group {} for this tenant".format(sg)
                    )

        if security_group_name is not None:
            self.security_groups_id = []
            for neutron_sg in neutron_sg_list:
                if security_group_name in (neutron_sg["id"], neutron_sg["name"]):
                    self.security_groups_id.append(neutron_sg["id"])
                    break
            else:
                self.security_groups_id = None
                raise vimconn.VimConnConnectionException(
                    "Not found security group {} for this tenant".format(sg)
                )

    def _find_nova_server(self, vm_id):
        """
        Returns the VM instance from Openstack and completes it with flavor ID
        Do not call nova.servers.find directly, as it does not return flavor ID with microversion>=2.47
        """
        try:
            self._reload_connection()
            server = self.nova.servers.find(id=vm_id)
            # TODO parse input and translate to VIM format (openmano_schemas.new_vminstance_response_schema)
            server_dict = server.to_dict()
            try:
                if server_dict["flavor"].get("original_name"):
                    server_dict["flavor"]["id"] = self.nova.flavors.find(
                        name=server_dict["flavor"]["original_name"]
                    ).id
            except nClient.exceptions.NotFound as e:
                self.logger.warning(str(e.message))
            return server_dict
        except (
            ksExceptions.ClientException,
            nvExceptions.ClientException,
            nvExceptions.NotFound,
            ConnectionError,
        ) as e:
            self._format_exception(e)

    def check_vim_connectivity(self):
        # just get network list to check connectivity and credentials
        self.get_network_list(filter_dict={})

    def get_tenant_list(self, filter_dict={}):
        """Obtain tenants of VIM
        filter_dict can contain the following keys:
            name: filter by tenant name
            id: filter by tenant uuid/id
            <other VIM specific>
        Returns the tenant list of dictionaries: [{'name':'<name>, 'id':'<id>, ...}, ...]
        """
        self.logger.debug("Getting tenants from VIM filter: '%s'", str(filter_dict))
        try:
            self._reload_connection()

            if self.api_version3:
                project_class_list = self.keystone.projects.list(
                    name=filter_dict.get("name")
                )
            else:
                project_class_list = self.keystone.tenants.findall(**filter_dict)

            project_list = []

            for project in project_class_list:
                if filter_dict.get("id") and filter_dict["id"] != project.id:
                    continue

                project_list.append(project.to_dict())

            return project_list
        except (
            ksExceptions.ConnectionError,
            ksExceptions.ClientException,
            ConnectionError,
        ) as e:
            self._format_exception(e)

    def new_tenant(self, tenant_name, tenant_description):
        """Adds a new tenant to openstack VIM. Returns the tenant identifier"""
        self.logger.debug("Adding a new tenant name: %s", tenant_name)
        try:
            self._reload_connection()

            if self.api_version3:
                project = self.keystone.projects.create(
                    tenant_name,
                    self.config.get("project_domain_id", "default"),
                    description=tenant_description,
                    is_domain=False,
                )
            else:
                project = self.keystone.tenants.create(tenant_name, tenant_description)

            return project.id
        except (
            ksExceptions.ConnectionError,
            ksExceptions.ClientException,
            ksExceptions.BadRequest,
            ConnectionError,
        ) as e:
            self._format_exception(e)

    def delete_tenant(self, tenant_id):
        """Delete a tenant from openstack VIM. Returns the old tenant identifier"""
        self.logger.debug("Deleting tenant %s from VIM", tenant_id)
        try:
            self._reload_connection()

            if self.api_version3:
                self.keystone.projects.delete(tenant_id)
            else:
                self.keystone.tenants.delete(tenant_id)

            return tenant_id

        except (
            ksExceptions.ConnectionError,
            ksExceptions.ClientException,
            ksExceptions.NotFound,
            ConnectionError,
        ) as e:
            self._format_exception(e)

    def new_network(
        self,
        net_name,
        net_type,
        ip_profile=None,
        shared=False,
        provider_network_profile=None,
    ):
        """Adds a tenant network to VIM
        Params:
            'net_name': name of the network
            'net_type': one of:
                'bridge': overlay isolated network
                'data':   underlay E-LAN network for Passthrough and SRIOV interfaces
                'ptp':    underlay E-LINE network for Passthrough and SRIOV interfaces.
            'ip_profile': is a dict containing the IP parameters of the network
                'ip_version': can be "IPv4" or "IPv6" (Currently only IPv4 is implemented)
                'subnet_address': ip_prefix_schema, that is X.X.X.X/Y
                'gateway_address': (Optional) ip_schema, that is X.X.X.X
                'dns_address': (Optional) comma separated list of ip_schema, e.g. X.X.X.X[,X,X,X,X]
                'dhcp_enabled': True or False
                'dhcp_start_address': ip_schema, first IP to grant
                'dhcp_count': number of IPs to grant.
            'shared': if this network can be seen/use by other tenants/organization
            'provider_network_profile': (optional) contains {segmentation-id: vlan, network-type: vlan|vxlan,
                                                             physical-network: physnet-label}
        Returns a tuple with the network identifier and created_items, or raises an exception on error
            created_items can be None or a dictionary where this method can include key-values that will be passed to
            the method delete_network. Can be used to store created segments, created l2gw connections, etc.
            Format is vimconnector dependent, but do not use nested dictionaries and a value of None should be the same
            as not present.
        """
        self.logger.debug(
            "Adding a new network to VIM name '%s', type '%s'", net_name, net_type
        )
        # self.logger.debug(">>>>>>>>>>>>>>>>>> IP profile %s", str(ip_profile))

        try:
            vlan = None

            if provider_network_profile:
                vlan = provider_network_profile.get("segmentation-id")

            new_net = None
            created_items = {}
            self._reload_connection()
            network_dict = {"name": net_name, "admin_state_up": True}

            if net_type in ("data", "ptp") or provider_network_profile:
                provider_physical_network = None

                if provider_network_profile and provider_network_profile.get(
                    "physical-network"
                ):
                    provider_physical_network = provider_network_profile.get(
                        "physical-network"
                    )

                    # provider-network must be one of the dataplane_physcial_netowrk if this is a list. If it is string
                    # or not declared, just ignore the checking
                    if (
                        isinstance(
                            self.config.get("dataplane_physical_net"), (tuple, list)
                        )
                        and provider_physical_network
                        not in self.config["dataplane_physical_net"]
                    ):
                        raise vimconn.VimConnConflictException(
                            "Invalid parameter 'provider-network:physical-network' "
                            "for network creation. '{}' is not one of the declared "
                            "list at VIM_config:dataplane_physical_net".format(
                                provider_physical_network
                            )
                        )

                # use the default dataplane_physical_net
                if not provider_physical_network:
                    provider_physical_network = self.config.get(
                        "dataplane_physical_net"
                    )

                    # if it is non-empty list, use the first value. If it is a string use the value directly
                    if (
                        isinstance(provider_physical_network, (tuple, list))
                        and provider_physical_network
                    ):
                        provider_physical_network = provider_physical_network[0]

                if not provider_physical_network:
                    raise vimconn.VimConnConflictException(
                        "missing information needed for underlay networks. Provide "
                        "'dataplane_physical_net' configuration at VIM or use the NS "
                        "instantiation parameter 'provider-network.physical-network'"
                        " for the VLD"
                    )

                if not self.config.get("multisegment_support"):
                    network_dict["provider:physical_network"] = (
                        provider_physical_network
                    )

                    if (
                        provider_network_profile
                        and "network-type" in provider_network_profile
                    ):
                        network_dict["provider:network_type"] = (
                            provider_network_profile["network-type"]
                        )
                    else:
                        network_dict["provider:network_type"] = self.config.get(
                            "dataplane_network_type", "vlan"
                        )

                    if vlan:
                        network_dict["provider:segmentation_id"] = vlan
                else:
                    # Multi-segment case
                    segment_list = []
                    segment1_dict = {
                        "provider:physical_network": "",
                        "provider:network_type": "vxlan",
                    }
                    segment_list.append(segment1_dict)
                    segment2_dict = {
                        "provider:physical_network": provider_physical_network,
                        "provider:network_type": "vlan",
                    }

                    if vlan:
                        segment2_dict["provider:segmentation_id"] = vlan
                    elif self.config.get("multisegment_vlan_range"):
                        vlanID = self._generate_multisegment_vlanID()
                        segment2_dict["provider:segmentation_id"] = vlanID

                    # else
                    #     raise vimconn.VimConnConflictException(
                    #         "You must provide "multisegment_vlan_range" at config dict before creating a multisegment
                    #         network")
                    segment_list.append(segment2_dict)
                    network_dict["segments"] = segment_list

                # VIO Specific Changes. It needs a concrete VLAN
                if self.vim_type == "VIO" and vlan is None:
                    if self.config.get("dataplane_net_vlan_range") is None:
                        raise vimconn.VimConnConflictException(
                            "You must provide 'dataplane_net_vlan_range' in format "
                            "[start_ID - end_ID] at VIM_config for creating underlay "
                            "networks"
                        )

                    network_dict["provider:segmentation_id"] = self._generate_vlanID()

            network_dict["shared"] = shared

            if self.config.get("disable_network_port_security"):
                network_dict["port_security_enabled"] = False

            if self.config.get("neutron_availability_zone_hints"):
                hints = self.config.get("neutron_availability_zone_hints")

                if isinstance(hints, str):
                    hints = [hints]

                network_dict["availability_zone_hints"] = hints

            new_net = self.neutron.create_network({"network": network_dict})
            # print new_net
            # create subnetwork, even if there is no profile

            if not ip_profile:
                ip_profile = {}

            if not ip_profile.get("subnet_address"):
                # Fake subnet is required
                subnet_rand = random.SystemRandom().randint(0, 255)
                ip_profile["subnet_address"] = "192.168.{}.0/24".format(subnet_rand)

            if "ip_version" not in ip_profile:
                ip_profile["ip_version"] = "IPv4"

            subnet = {
                "name": net_name + "-subnet",
                "network_id": new_net["network"]["id"],
                "ip_version": 4 if ip_profile["ip_version"] == "IPv4" else 6,
                "cidr": ip_profile["subnet_address"],
            }

            # Gateway should be set to None if not needed. Otherwise openstack assigns one by default
            if ip_profile.get("gateway_address"):
                subnet["gateway_ip"] = ip_profile["gateway_address"]
            else:
                subnet["gateway_ip"] = None

            if ip_profile.get("dns_address"):
                subnet["dns_nameservers"] = ip_profile["dns_address"].split(";")

            if "dhcp_enabled" in ip_profile:
                subnet["enable_dhcp"] = (
                    False
                    if ip_profile["dhcp_enabled"] == "false"
                    or ip_profile["dhcp_enabled"] is False
                    else True
                )

            if ip_profile.get("dhcp_start_address"):
                subnet["allocation_pools"] = []
                subnet["allocation_pools"].append(dict())
                subnet["allocation_pools"][0]["start"] = ip_profile[
                    "dhcp_start_address"
                ]

            if ip_profile.get("dhcp_count"):
                # parts = ip_profile["dhcp_start_address"].split(".")
                # ip_int = (int(parts[0]) << 24) + (int(parts[1]) << 16) + (int(parts[2]) << 8) + int(parts[3])
                ip_int = int(netaddr.IPAddress(ip_profile["dhcp_start_address"]))
                ip_int += ip_profile["dhcp_count"] - 1
                ip_str = str(netaddr.IPAddress(ip_int))
                subnet["allocation_pools"][0]["end"] = ip_str

            if (
                ip_profile.get("ipv6_address_mode")
                and ip_profile["ip_version"] != "IPv4"
            ):
                subnet["ipv6_address_mode"] = ip_profile["ipv6_address_mode"]
                # ipv6_ra_mode can be set to the same value for most use cases, see documentation:
                # https://docs.openstack.org/neutron/latest/admin/config-ipv6.html#ipv6-ra-mode-and-ipv6-address-mode-combinations
                subnet["ipv6_ra_mode"] = ip_profile["ipv6_address_mode"]

            # self.logger.debug(">>>>>>>>>>>>>>>>>> Subnet: %s", str(subnet))
            self.neutron.create_subnet({"subnet": subnet})

            if net_type == "data" and self.config.get("multisegment_support"):
                if self.config.get("l2gw_support"):
                    l2gw_list = self.neutron.list_l2_gateways().get("l2_gateways", ())
                    for l2gw in l2gw_list:
                        l2gw_conn = {
                            "l2_gateway_id": l2gw["id"],
                            "network_id": new_net["network"]["id"],
                            "segmentation_id": str(vlanID),
                        }
                        new_l2gw_conn = self.neutron.create_l2_gateway_connection(
                            {"l2_gateway_connection": l2gw_conn}
                        )
                        created_items[
                            "l2gwconn:"
                            + str(new_l2gw_conn["l2_gateway_connection"]["id"])
                        ] = True

            return new_net["network"]["id"], created_items
        except Exception as e:
            # delete l2gw connections (if any) before deleting the network
            for k, v in created_items.items():
                if not v:  # skip already deleted
                    continue

                try:
                    k_item, _, k_id = k.partition(":")

                    if k_item == "l2gwconn":
                        self.neutron.delete_l2_gateway_connection(k_id)

                except (neExceptions.ConnectionFailed, ConnectionError) as e2:
                    self.logger.error(
                        "Error deleting l2 gateway connection: {}: {}".format(
                            type(e2).__name__, e2
                        )
                    )
                    self._format_exception(e2)
                except Exception as e2:
                    self.logger.error(
                        "Error deleting l2 gateway connection: {}: {}".format(
                            type(e2).__name__, e2
                        )
                    )

            if new_net:
                self.neutron.delete_network(new_net["network"]["id"])

            self._format_exception(e)

    def get_network_list(self, filter_dict={}):
        """Obtain tenant networks of VIM
        Filter_dict can be:
            name: network name
            id: network uuid
            shared: boolean
            tenant_id: tenant
            admin_state_up: boolean
            status: 'ACTIVE'
        Returns the network list of dictionaries
        """
        self.logger.debug("Getting network from VIM filter: '%s'", str(filter_dict))
        try:
            self._reload_connection()
            filter_dict_os = filter_dict.copy()

            if self.api_version3 and "tenant_id" in filter_dict_os:
                # TODO check
                filter_dict_os["project_id"] = filter_dict_os.pop("tenant_id")

            net_dict = self.neutron.list_networks(**filter_dict_os)
            net_list = net_dict["networks"]
            self.__net_os2mano(net_list)

            return net_list
        except (
            neExceptions.ConnectionFailed,
            ksExceptions.ClientException,
            neExceptions.NeutronException,
            ConnectionError,
        ) as e:
            self._format_exception(e)

    def get_network(self, net_id):
        """Obtain details of network from VIM
        Returns the network information from a network id"""
        self.logger.debug(" Getting tenant network %s from VIM", net_id)
        filter_dict = {"id": net_id}
        net_list = self.get_network_list(filter_dict)

        if len(net_list) == 0:
            raise vimconn.VimConnNotFoundException(
                "Network '{}' not found".format(net_id)
            )
        elif len(net_list) > 1:
            raise vimconn.VimConnConflictException(
                "Found more than one network with this criteria"
            )

        net = net_list[0]
        subnets = []
        for subnet_id in net.get("subnets", ()):
            try:
                subnet = self.neutron.show_subnet(subnet_id)
            except Exception as e:
                self.logger.error(
                    "osconnector.get_network(): Error getting subnet %s %s"
                    % (net_id, str(e))
                )
                subnet = {"id": subnet_id, "fault": str(e)}

            subnets.append(subnet)

        net["subnets"] = subnets
        net["encapsulation"] = net.get("provider:network_type")
        net["encapsulation_type"] = net.get("provider:network_type")
        net["segmentation_id"] = net.get("provider:segmentation_id")
        net["encapsulation_id"] = net.get("provider:segmentation_id")

        return net

    @catch_any_exception
    def delete_network(self, net_id, created_items=None):
        """
        Removes a tenant network from VIM and its associated elements
        :param net_id: VIM identifier of the network, provided by method new_network
        :param created_items: dictionary with extra items to be deleted. provided by method new_network
        Returns the network identifier or raises an exception upon error or when network is not found
        """
        self.logger.debug("Deleting network '%s' from VIM", net_id)

        if created_items is None:
            created_items = {}

        try:
            self._reload_connection()
            # delete l2gw connections (if any) before deleting the network
            for k, v in created_items.items():
                if not v:  # skip already deleted
                    continue

                try:
                    k_item, _, k_id = k.partition(":")
                    if k_item == "l2gwconn":
                        self.neutron.delete_l2_gateway_connection(k_id)

                except (neExceptions.ConnectionFailed, ConnectionError) as e:
                    self.logger.error(
                        "Error deleting l2 gateway connection: {}: {}".format(
                            type(e).__name__, e
                        )
                    )
                    self._format_exception(e)
                except Exception as e:
                    self.logger.error(
                        "Error deleting l2 gateway connection: {}: {}".format(
                            type(e).__name__, e
                        )
                    )

            # delete VM ports attached to this networks before the network
            ports = self.neutron.list_ports(network_id=net_id)
            for p in ports["ports"]:
                try:
                    self.neutron.delete_port(p["id"])

                except (neExceptions.ConnectionFailed, ConnectionError) as e:
                    self.logger.error("Error deleting port %s: %s", p["id"], str(e))
                    # If there is connection error, it raises.
                    self._format_exception(e)
                except Exception as e:
                    self.logger.error("Error deleting port %s: %s", p["id"], str(e))

            self.neutron.delete_network(net_id)

            return net_id
        except (neExceptions.NetworkNotFoundClient, neExceptions.NotFound) as e:
            # If network to be deleted is not found, it does not raise.
            self.logger.warning(
                f"Error deleting network: {net_id} is not found, {str(e)}"
            )

    def refresh_nets_status(self, net_list):
        """Get the status of the networks
        Params: the list of network identifiers
        Returns a dictionary with:
            net_id:         #VIM id of this network
                status:     #Mandatory. Text with one of:
                            #  DELETED (not found at vim)
                            #  VIM_ERROR (Cannot connect to VIM, VIM response error, ...)
                            #  OTHER (Vim reported other status not understood)
                            #  ERROR (VIM indicates an ERROR status)
                            #  ACTIVE, INACTIVE, DOWN (admin down),
                            #  BUILD (on building process)
                            #
                error_msg:  #Text with VIM error message, if any. Or the VIM connection ERROR
                vim_info:   #Text with plain information obtained from vim (yaml.safe_dump)
        """
        net_dict = {}

        for net_id in net_list:
            net = {}

            try:
                net_vim = self.get_network(net_id)

                if net_vim["status"] in netStatus2manoFormat:
                    net["status"] = netStatus2manoFormat[net_vim["status"]]
                else:
                    net["status"] = "OTHER"
                    net["error_msg"] = "VIM status reported " + net_vim["status"]

                if net["status"] == "ACTIVE" and not net_vim["admin_state_up"]:
                    net["status"] = "DOWN"

                net["vim_info"] = self.serialize(net_vim)

                if net_vim.get("fault"):  # TODO
                    net["error_msg"] = str(net_vim["fault"])
            except vimconn.VimConnNotFoundException as e:
                self.logger.error("Exception getting net status: %s", str(e))
                net["status"] = "DELETED"
                net["error_msg"] = str(e)
            except vimconn.VimConnException as e:
                self.logger.error("Exception getting net status: %s", str(e))
                net["status"] = "VIM_ERROR"
                net["error_msg"] = str(e)
            net_dict[net_id] = net
        return net_dict

    def get_flavor(self, flavor_id=None, flavor_name=None):
        """Obtain flavor details from the  VIM. Returns the flavor dict details"""
        self.logger.debug("Getting flavor '%s'", flavor_id)
        try:
            self._reload_connection()
            if flavor_id:
                flavor = self.nova.flavors.find(id=flavor_id)
            else:
                flavor = self.nova.flavors.find(name=flavor_name)
            return flavor.to_dict()

        except (
            nvExceptions.NotFound,
            nvExceptions.ClientException,
            ksExceptions.ClientException,
            ConnectionError,
        ) as e:
            self._format_exception(e)

    def get_flavor_id_from_data(self, flavor_dict):
        """Obtain flavor id that match the flavor description
        Returns the flavor_id or raises a vimconnNotFoundException
        flavor_dict: contains the required ram, vcpus, disk
        If 'use_existing_flavors' is set to True at config, the closer flavor that provides same or more ram, vcpus
            and disk is returned. Otherwise a flavor with exactly same ram, vcpus and disk is returned or a
            vimconnNotFoundException is raised
        """
        exact_match = False if self.config.get("use_existing_flavors") else True

        try:
            self._reload_connection()
            flavor_candidate_id = None
            flavor_candidate_data = (10000, 10000, 10000)
            flavor_target = (
                flavor_dict["ram"],
                flavor_dict["vcpus"],
                flavor_dict["disk"],
                flavor_dict.get("ephemeral", 0),
                flavor_dict.get("swap", 0),
            )
            # numa=None
            extended = flavor_dict.get("extended", {})
            if extended:
                # TODO
                raise vimconn.VimConnNotFoundException(
                    "Flavor with EPA still not implemented"
                )
                # if len(numas) > 1:
                #     raise vimconn.VimConnNotFoundException("Cannot find any flavor with more than one numa")
                # numa=numas[0]
                # numas = extended.get("numas")
            for flavor in self.nova.flavors.list():
                epa = flavor.get_keys()

                if epa:
                    continue
                    # TODO

                flavor_data = (
                    flavor.ram,
                    flavor.vcpus,
                    flavor.disk,
                    flavor.ephemeral,
                    flavor.swap if isinstance(flavor.swap, int) else 0,
                )
                if flavor_data == flavor_target:
                    return flavor.id
                elif (
                    not exact_match
                    and flavor_target < flavor_data < flavor_candidate_data
                ):
                    flavor_candidate_id = flavor.id
                    flavor_candidate_data = flavor_data

            if not exact_match and flavor_candidate_id:
                return flavor_candidate_id

            raise vimconn.VimConnNotFoundException(
                "Cannot find any flavor matching '{}'".format(flavor_dict)
            )
        except (
            nvExceptions.NotFound,
            nvExceptions.BadRequest,
            nvExceptions.ClientException,
            ksExceptions.ClientException,
            ConnectionError,
        ) as e:
            self._format_exception(e)

    @staticmethod
    def process_resource_quota(quota: dict, prefix: str, extra_specs: dict) -> None:
        """Process resource quota and fill up extra_specs.
        Args:
            quota       (dict):         Keeping the quota of resurces
            prefix      (str)           Prefix
            extra_specs (dict)          Dict to be filled to be used during flavor creation

        """
        if "limit" in quota:
            extra_specs["quota:" + prefix + "_limit"] = quota["limit"]

        if "reserve" in quota:
            extra_specs["quota:" + prefix + "_reservation"] = quota["reserve"]

        if "shares" in quota:
            extra_specs["quota:" + prefix + "_shares_level"] = "custom"
            extra_specs["quota:" + prefix + "_shares_share"] = quota["shares"]

    @staticmethod
    def process_numa_memory(
        numa: dict, node_id: Optional[int], extra_specs: dict
    ) -> None:
        """Set the memory in extra_specs.
        Args:
            numa        (dict):         A dictionary which includes numa information
            node_id     (int):          ID of numa node
            extra_specs (dict):         To be filled.

        """
        if not numa.get("memory"):
            return
        memory_mb = numa["memory"] * 1024
        memory = "hw:numa_mem.{}".format(node_id)
        extra_specs[memory] = int(memory_mb)

    @staticmethod
    def process_numa_vcpu(numa: dict, node_id: int, extra_specs: dict) -> None:
        """Set the cpu in extra_specs.
        Args:
            numa        (dict):         A dictionary which includes numa information
            node_id     (int):          ID of numa node
            extra_specs (dict):         To be filled.

        """
        if not numa.get("vcpu"):
            return
        vcpu = numa["vcpu"]
        cpu = "hw:numa_cpus.{}".format(node_id)
        vcpu = ",".join(map(str, vcpu))
        extra_specs[cpu] = vcpu

    @staticmethod
    def process_numa_paired_threads(numa: dict, extra_specs: dict) -> Optional[int]:
        """Fill up extra_specs if numa has paired-threads.
        Args:
            numa        (dict):         A dictionary which includes numa information
            extra_specs (dict):         To be filled.

        Returns:
            threads       (int)           Number of virtual cpus

        """
        if not numa.get("paired-threads"):
            return

        # cpu_thread_policy "require" implies that compute node must have an STM architecture
        threads = numa["paired-threads"] * 2
        extra_specs["hw:cpu_thread_policy"] = "require"
        extra_specs["hw:cpu_policy"] = "dedicated"
        return threads

    @staticmethod
    def process_numa_cores(numa: dict, extra_specs: dict) -> Optional[int]:
        """Fill up extra_specs if numa has cores.
        Args:
            numa        (dict):         A dictionary which includes numa information
            extra_specs (dict):         To be filled.

        Returns:
            cores       (int)           Number of virtual cpus

        """
        # cpu_thread_policy "isolate" implies that the host must not have an SMT
        # architecture, or a non-SMT architecture will be emulated
        if not numa.get("cores"):
            return
        cores = numa["cores"]
        extra_specs["hw:cpu_thread_policy"] = "isolate"
        extra_specs["hw:cpu_policy"] = "dedicated"
        return cores

    @staticmethod
    def process_numa_threads(numa: dict, extra_specs: dict) -> Optional[int]:
        """Fill up extra_specs if numa has threads.
        Args:
            numa        (dict):         A dictionary which includes numa information
            extra_specs (dict):         To be filled.

        Returns:
            threads       (int)           Number of virtual cpus

        """
        # cpu_thread_policy "prefer" implies that the host may or may not have an SMT architecture
        if not numa.get("threads"):
            return
        threads = numa["threads"]
        extra_specs["hw:cpu_thread_policy"] = "prefer"
        extra_specs["hw:cpu_policy"] = "dedicated"
        return threads

    def _process_numa_parameters_of_flavor(
        self, numas: List, extra_specs: Dict
    ) -> None:
        """Process numa parameters and fill up extra_specs.

        Args:
            numas   (list):             List of dictionary which includes numa information
            extra_specs (dict):         To be filled.

        """
        numa_nodes = len(numas)
        extra_specs["hw:numa_nodes"] = str(numa_nodes)
        cpu_cores, cpu_threads = 0, 0

        if self.vim_type == "VIO":
            self.process_vio_numa_nodes(numa_nodes, extra_specs)

        for numa in numas:
            if "id" in numa:
                node_id = numa["id"]
                # overwrite ram and vcpus
                # check if key "memory" is present in numa else use ram value at flavor
                self.process_numa_memory(numa, node_id, extra_specs)
                self.process_numa_vcpu(numa, node_id, extra_specs)

            # See for reference: https://specs.openstack.org/openstack/nova-specs/specs/mitaka/implemented/virt-driver-cpu-thread-pinning.html
            extra_specs["hw:cpu_sockets"] = str(numa_nodes)

            if "paired-threads" in numa:
                threads = self.process_numa_paired_threads(numa, extra_specs)
                cpu_threads += threads

            elif "cores" in numa:
                cores = self.process_numa_cores(numa, extra_specs)
                cpu_cores += cores

            elif "threads" in numa:
                threads = self.process_numa_threads(numa, extra_specs)
                cpu_threads += threads

        if cpu_cores:
            extra_specs["hw:cpu_cores"] = str(cpu_cores)
        if cpu_threads:
            extra_specs["hw:cpu_threads"] = str(cpu_threads)

    @staticmethod
    def process_vio_numa_nodes(numa_nodes: int, extra_specs: Dict) -> None:
        """According to number of numa nodes, updates the extra_specs for VIO.

        Args:

            numa_nodes      (int):         List keeps the numa node numbers
            extra_specs     (dict):        Extra specs dict to be updated

        """
        # If there are several numas, we do not define specific affinity.
        extra_specs["vmware:latency_sensitivity_level"] = "high"

    def _change_flavor_name(
        self, name: str, name_suffix: int, flavor_data: dict
    ) -> str:
        """Change the flavor name if the name already exists.

        Args:
            name    (str):          Flavor name to be checked
            name_suffix (int):      Suffix to be appended to name
            flavor_data (dict):     Flavor dict

        Returns:
            name    (str):          New flavor name to be used

        """
        # Get used names
        fl = self.nova.flavors.list()
        fl_names = [f.name for f in fl]

        while name in fl_names:
            name_suffix += 1
            name = flavor_data["name"] + "-" + str(name_suffix)

        return name

    def _process_extended_config_of_flavor(
        self, extended: dict, extra_specs: dict
    ) -> None:
        """Process the extended dict to fill up extra_specs.
        Args:

            extended                    (dict):         Keeping the extra specification of flavor
            extra_specs                 (dict)          Dict to be filled to be used during flavor creation

        """
        quotas = {
            "cpu-quota": "cpu",
            "mem-quota": "memory",
            "vif-quota": "vif",
            "disk-io-quota": "disk_io",
        }

        page_sizes = {
            "LARGE": "large",
            "SMALL": "small",
            "SIZE_2MB": "2MB",
            "SIZE_1GB": "1GB",
            "PREFER_LARGE": "any",
        }

        policies = {
            "cpu-pinning-policy": "hw:cpu_policy",
            "cpu-thread-pinning-policy": "hw:cpu_thread_policy",
            "mem-policy": "hw:numa_mempolicy",
        }

        numas = extended.get("numas")
        if numas:
            self._process_numa_parameters_of_flavor(numas, extra_specs)

        for quota, item in quotas.items():
            if quota in extended.keys():
                self.process_resource_quota(extended.get(quota), item, extra_specs)

        # Set the mempage size as specified in the descriptor
        if extended.get("mempage-size"):
            if extended["mempage-size"] in page_sizes.keys():
                extra_specs["hw:mem_page_size"] = page_sizes[extended["mempage-size"]]
            else:
                # Normally, validations in NBI should not allow to this condition.
                self.logger.debug(
                    "Invalid mempage-size %s. Will be ignored",
                    extended.get("mempage-size"),
                )

        for policy, hw_policy in policies.items():
            if extended.get(policy):
                extra_specs[hw_policy] = extended[policy].lower()

    @staticmethod
    def _get_flavor_details(flavor_data: dict) -> Tuple:
        """Returns the details of flavor
        Args:
            flavor_data     (dict):     Dictionary that includes required flavor details

        Returns:
            ram, vcpus, extra_specs, extended   (tuple):    Main items of required flavor

        """
        return (
            flavor_data.get("ram", 64),
            flavor_data.get("vcpus", 1),
            {},
            flavor_data.get("extended"),
        )

    @catch_any_exception
    def new_flavor(self, flavor_data: dict, change_name_if_used: bool = True) -> str:
        """Adds a tenant flavor to openstack VIM.
        if change_name_if_used is True, it will change name in case of conflict,
        because it is not supported name repetition.

        Args:
            flavor_data (dict):             Flavor details to be processed
            change_name_if_used (bool):     Change name in case of conflict

        Returns:
             flavor_id  (str):     flavor identifier

        """
        self.logger.debug("Adding flavor '%s'", str(flavor_data))
        retry = 0
        max_retries = 3
        name_suffix = 0
        name = flavor_data["name"]
        while retry < max_retries:
            retry += 1
            try:
                self._reload_connection()

                if change_name_if_used:
                    name = self._change_flavor_name(name, name_suffix, flavor_data)

                ram, vcpus, extra_specs, extended = self._get_flavor_details(
                    flavor_data
                )
                if extended:
                    self._process_extended_config_of_flavor(extended, extra_specs)

                # Create flavor

                new_flavor = self.nova.flavors.create(
                    name=name,
                    ram=ram,
                    vcpus=vcpus,
                    disk=flavor_data.get("disk", 0),
                    ephemeral=flavor_data.get("ephemeral", 0),
                    swap=flavor_data.get("swap", 0),
                    is_public=flavor_data.get("is_public", True),
                )

                # Add metadata
                if extra_specs:
                    new_flavor.set_keys(extra_specs)

                return new_flavor.id

            except nvExceptions.Conflict as e:
                if change_name_if_used and retry < max_retries:
                    continue

                self._format_exception(e)

    @catch_any_exception
    def delete_flavor(self, flavor_id):
        """Deletes a tenant flavor from openstack VIM. Returns the old flavor_id"""
        try:
            self._reload_connection()
            self.nova.flavors.delete(flavor_id)
            return flavor_id

        except (nvExceptions.NotFound, nvExceptions.ResourceNotFound) as e:
            # If flavor is not found, it does not raise.
            self.logger.warning(
                f"Error deleting flavor: {flavor_id} is not found, {str(e.message)}"
            )

    def new_image(self, image_dict):
        """
        Adds a tenant image to VIM. imge_dict is a dictionary with:
            name: name
            disk_format: qcow2, vhd, vmdk, raw (by default), ...
            location: path or URI
            public: "yes" or "no"
            metadata: metadata of the image
        Returns the image_id
        """
        retry = 0
        max_retries = 3

        while retry < max_retries:
            retry += 1
            try:
                self._reload_connection()

                # determine format  http://docs.openstack.org/developer/glance/formats.html
                if "disk_format" in image_dict:
                    disk_format = image_dict["disk_format"]
                else:  # autodiscover based on extension
                    if image_dict["location"].endswith(".qcow2"):
                        disk_format = "qcow2"
                    elif image_dict["location"].endswith(".vhd"):
                        disk_format = "vhd"
                    elif image_dict["location"].endswith(".vmdk"):
                        disk_format = "vmdk"
                    elif image_dict["location"].endswith(".vdi"):
                        disk_format = "vdi"
                    elif image_dict["location"].endswith(".iso"):
                        disk_format = "iso"
                    elif image_dict["location"].endswith(".aki"):
                        disk_format = "aki"
                    elif image_dict["location"].endswith(".ari"):
                        disk_format = "ari"
                    elif image_dict["location"].endswith(".ami"):
                        disk_format = "ami"
                    else:
                        disk_format = "raw"

                self.logger.debug(
                    "new_image: '%s' loading from '%s'",
                    image_dict["name"],
                    image_dict["location"],
                )
                if self.vim_type == "VIO":
                    container_format = "bare"
                    if "container_format" in image_dict:
                        container_format = image_dict["container_format"]

                    new_image = self.glance.images.create(
                        name=image_dict["name"],
                        container_format=container_format,
                        disk_format=disk_format,
                    )
                else:
                    new_image = self.glance.images.create(name=image_dict["name"])

                if image_dict["location"].startswith("http"):
                    # TODO there is not a method to direct download. It must be downloaded locally with requests
                    raise vimconn.VimConnNotImplemented("Cannot create image from URL")
                else:  # local path
                    with open(image_dict["location"]) as fimage:
                        self.glance.images.upload(new_image.id, fimage)
                        # new_image = self.glancev1.images.create(name=image_dict["name"], is_public=
                        #  image_dict.get("public","yes")=="yes",
                        #    container_format="bare", data=fimage, disk_format=disk_format)

                metadata_to_load = image_dict.get("metadata")

                # TODO location is a reserved word for current openstack versions. fixed for VIO please check
                #  for openstack
                if self.vim_type == "VIO":
                    metadata_to_load["upload_location"] = image_dict["location"]
                else:
                    metadata_to_load["location"] = image_dict["location"]

                self.glance.images.update(new_image.id, **metadata_to_load)

                return new_image.id
            except (
                HTTPException,
                gl1Exceptions.HTTPException,
                gl1Exceptions.CommunicationError,
                ConnectionError,
            ) as e:
                if retry == max_retries:
                    continue

                self._format_exception(e)
            except IOError as e:  # can not open the file
                raise vimconn.VimConnConnectionException(
                    "{}: {} for {}".format(type(e).__name__, e, image_dict["location"]),
                    http_code=vimconn.HTTP_Bad_Request,
                )
            except Exception as e:
                self._format_exception(e)

    @catch_any_exception
    def delete_image(self, image_id):
        """Deletes a tenant image from openstack VIM. Returns the old id"""
        try:
            self._reload_connection()
            self.glance.images.delete(image_id)

            return image_id
        except gl1Exceptions.NotFound as e:
            # If image is not found, it does not raise.
            self.logger.warning(
                f"Error deleting image: {image_id} is not found, {str(e)}"
            )

    @catch_any_exception
    def get_image_id_from_path(self, path):
        """Get the image id from image path in the VIM database. Returns the image_id"""
        self._reload_connection()
        images = self.glance.images.list()

        for image in images:
            if image.metadata.get("location") == path:
                return image.id

        raise vimconn.VimConnNotFoundException(
            "image with location '{}' not found".format(path)
        )

    def get_image_list(self, filter_dict={}):
        """Obtain tenant images from VIM
        Filter_dict can be:
            id: image id
            name: image name
            checksum: image checksum
        Returns the image list of dictionaries:
            [{<the fields at Filter_dict plus some VIM specific>}, ...]
            List can be empty
        """
        self.logger.debug("Getting image list from VIM filter: '%s'", str(filter_dict))
        try:
            self._reload_connection()
            # filter_dict_os = filter_dict.copy()
            # First we filter by the available filter fields: name, id. The others are removed.
            image_list = self.glance.images.list()
            filtered_list = []

            for image in image_list:
                try:
                    if filter_dict.get("name") and image["name"] != filter_dict["name"]:
                        continue

                    if filter_dict.get("id") and image["id"] != filter_dict["id"]:
                        continue

                    if (
                        filter_dict.get("checksum")
                        and image["checksum"] != filter_dict["checksum"]
                    ):
                        continue

                    filtered_list.append(image.copy())
                except gl1Exceptions.HTTPNotFound:
                    pass

            return filtered_list

        except (
            ksExceptions.ClientException,
            nvExceptions.ClientException,
            gl1Exceptions.CommunicationError,
            ConnectionError,
        ) as e:
            self._format_exception(e)

    def __wait_for_vm(self, vm_id, status):
        """wait until vm is in the desired status and return True.
        If the VM gets in ERROR status, return false.
        If the timeout is reached generate an exception"""
        elapsed_time = 0
        while elapsed_time < server_timeout:
            vm_status = self.nova.servers.get(vm_id).status

            if vm_status == status:
                return True

            if vm_status == "ERROR":
                return False

            time.sleep(5)
            elapsed_time += 5

        # if we exceeded the timeout rollback
        if elapsed_time >= server_timeout:
            raise vimconn.VimConnException(
                "Timeout waiting for instance " + vm_id + " to get " + status,
                http_code=vimconn.HTTP_Request_Timeout,
            )

    def _get_openstack_availablity_zones(self):
        """
        Get from openstack availability zones available
        :return:
        """
        try:
            openstack_availability_zone = self.nova.availability_zones.list()
            openstack_availability_zone = [
                str(zone.zoneName)
                for zone in openstack_availability_zone
                if zone.zoneName != "internal"
            ]

            return openstack_availability_zone
        except Exception:
            return None

    def _set_availablity_zones(self):
        """
        Set vim availablity zone
        :return:
        """
        if "availability_zone" in self.config:
            vim_availability_zones = self.config.get("availability_zone")

            if isinstance(vim_availability_zones, str):
                self.availability_zone = [vim_availability_zones]
            elif isinstance(vim_availability_zones, list):
                self.availability_zone = vim_availability_zones
        else:
            self.availability_zone = self._get_openstack_availablity_zones()
        if "storage_availability_zone" in self.config:
            self.storage_availability_zone = self.config.get(
                "storage_availability_zone"
            )

    def _get_vm_availability_zone(
        self, availability_zone_index, availability_zone_list
    ):
        """
        Return thge availability zone to be used by the created VM.
        :return: The VIM availability zone to be used or None
        """
        if availability_zone_index is None:
            if not self.config.get("availability_zone"):
                return None
            elif isinstance(self.config.get("availability_zone"), str):
                return self.config["availability_zone"]
            else:
                # TODO consider using a different parameter at config for default AV and AV list match
                return self.config["availability_zone"][0]

        vim_availability_zones = self.availability_zone
        # check if VIM offer enough availability zones describe in the VNFD
        if vim_availability_zones and len(availability_zone_list) <= len(
            vim_availability_zones
        ):
            # check if all the names of NFV AV match VIM AV names
            match_by_index = False
            for av in availability_zone_list:
                if av not in vim_availability_zones:
                    match_by_index = True
                    break

            if match_by_index:
                return vim_availability_zones[availability_zone_index]
            else:
                return availability_zone_list[availability_zone_index]
        else:
            raise vimconn.VimConnConflictException(
                "No enough availability zones at VIM for this deployment"
            )

    def _prepare_port_dict_security_groups(
        self, net: dict, port_dict: dict, security_group_name=None
    ) -> None:
        """Fill up the security_groups in the port_dict.

        Args:
            net (dict):             Network details
            port_dict   (dict):     Port details

        """
        if (
            self.config.get("security_groups")
            and net.get("port_security") is not False
            and not self.config.get("no_port_security_extension")
        ):
            if not self.security_groups_id:
                self._get_ids_from_name()

            port_dict["security_groups"] = self.security_groups_id

            if security_group_name is not None:
                self._get_ids_from_name(security_group_name)
                port_dict["security_groups"] = self.security_groups_id

    def _prepare_port_dict_binding(self, net: dict, port_dict: dict) -> None:
        """Fill up the network binding depending on network type in the port_dict.

        Args:
            net (dict):             Network details
            port_dict   (dict):     Port details

        """
        if not net.get("type"):
            raise vimconn.VimConnException("Type is missing in the network details.")

        if net["type"] == "virtual":
            pass

        # For VF
        elif net["type"] == "VF" or net["type"] == "SR-IOV":
            port_dict["binding:vnic_type"] = "direct"

            # VIO specific Changes
            if self.vim_type == "VIO":
                # Need to create port with port_security_enabled = False and no-security-groups
                port_dict["port_security_enabled"] = False
                port_dict["provider_security_groups"] = []
                port_dict["security_groups"] = []

        else:
            # For PT PCI-PASSTHROUGH
            port_dict["binding:vnic_type"] = "direct-physical"

    @staticmethod
    def _set_fixed_ip(new_port: dict, net: dict) -> None:
        """Set the "ip" parameter in net dictionary.

        Args:
            new_port    (dict):     New created port
            net         (dict):     Network details

        """
        fixed_ips = new_port["port"].get("fixed_ips")

        if fixed_ips:
            net["ip"] = fixed_ips[0].get("ip_address")
        else:
            net["ip"] = None

    @staticmethod
    def _prepare_port_dict_mac_ip_addr(net: dict, port_dict: dict) -> None:
        """Fill up the mac_address and fixed_ips in port_dict.

        Args:
            net (dict):             Network details
            port_dict   (dict):     Port details

        """
        if net.get("mac_address"):
            port_dict["mac_address"] = net["mac_address"]

        ip_dual_list = []
        if ip_list := net.get("ip_address"):
            if not isinstance(ip_list, list):
                ip_list = [ip_list]
            for ip in ip_list:
                ip_dict = {"ip_address": ip}
                ip_dual_list.append(ip_dict)
            port_dict["fixed_ips"] = ip_dual_list
            # TODO add "subnet_id": <subnet_id>

    def _create_new_port(self, port_dict: dict, created_items: dict, net: dict) -> Dict:
        """Create new port using neutron.

        Args:
            port_dict   (dict):         Port details
            created_items   (dict):     All created items
            net (dict):                 Network details

        Returns:
            new_port    (dict):         New created port

        """
        new_port = self.neutron.create_port({"port": port_dict})
        created_items["port:" + str(new_port["port"]["id"])] = True
        net["mac_address"] = new_port["port"]["mac_address"]
        net["vim_id"] = new_port["port"]["id"]

        return new_port

    def _create_port(
        self, net: dict, name: str, created_items: dict, security_group_name=None
    ) -> Tuple[dict, dict]:
        """Create port using net details.

        Args:
            net (dict):                 Network details
            name    (str):              Name to be used as network name if net dict does not include name
            created_items   (dict):     All created items

        Returns:
            new_port, port              New created port, port dictionary

        """

        port_dict = {
            "network_id": net["net_id"],
            "name": net.get("name"),
            "admin_state_up": True,
        }

        if not port_dict["name"]:
            port_dict["name"] = name

        self._prepare_port_dict_security_groups(net, port_dict, security_group_name)

        self._prepare_port_dict_binding(net, port_dict)

        vimconnector._prepare_port_dict_mac_ip_addr(net, port_dict)

        new_port = self._create_new_port(port_dict, created_items, net)

        vimconnector._set_fixed_ip(new_port, net)

        port = {"port-id": new_port["port"]["id"]}

        if float(self.nova.api_version.get_string()) >= 2.32:
            port["tag"] = new_port["port"]["name"]

        return new_port, port

    def _prepare_network_for_vminstance(
        self,
        name: str,
        net_list: list,
        created_items: dict,
        net_list_vim: list,
        external_network: list,
        no_secured_ports: list,
        security_group_name=None,
    ) -> None:
        """Create port and fill up net dictionary for new VM instance creation.

        Args:
            name    (str):                  Name of network
            net_list    (list):             List of networks
            created_items   (dict):         All created items belongs to a VM
            net_list_vim    (list):         List of ports
            external_network    (list):     List of external-networks
            no_secured_ports    (list):     Port security disabled ports
        """

        self._reload_connection()

        for net in net_list:
            # Skip non-connected iface
            if not net.get("net_id"):
                continue

            new_port, port = self._create_port(
                net, name, created_items, security_group_name
            )

            net_list_vim.append(port)

            if net.get("floating_ip", False):
                net["exit_on_floating_ip_error"] = True
                external_network.append(net)

            elif net["use"] == "mgmt" and self.config.get("use_floating_ip"):
                net["exit_on_floating_ip_error"] = False
                external_network.append(net)
                net["floating_ip"] = self.config.get("use_floating_ip")

            # If port security is disabled when the port has not yet been attached to the VM, then all vm traffic
            # is dropped. As a workaround we wait until the VM is active and then disable the port-security
            if net.get("port_security") is False and not self.config.get(
                "no_port_security_extension"
            ):
                no_secured_ports.append(
                    (
                        new_port["port"]["id"],
                        net.get("port_security_disable_strategy"),
                    )
                )

    def _prepare_persistent_root_volumes(
        self,
        name: str,
        storage_av_zone: list,
        disk: dict,
        base_disk_index: int,
        block_device_mapping: dict,
        existing_vim_volumes: list,
        created_items: dict,
    ) -> Optional[str]:
        """Prepare persistent root volumes for new VM instance.

        Args:
            name    (str):                      Name of VM instance
            storage_av_zone  (list):            Storage of availability zones
            disk    (dict):                     Disk details
            base_disk_index (int):              Disk index
            block_device_mapping    (dict):     Block device details
            existing_vim_volumes    (list):     Existing disk details
            created_items   (dict):             All created items belongs to VM

        Returns:
            boot_volume_id  (str):              ID of boot volume

        """
        self.logger.debug("Preparing root persistent volumes")
        # Disk may include only vim_volume_id or only vim_id."
        # Use existing persistent root volume finding with volume_id or vim_id
        key_id = "vim_volume_id" if "vim_volume_id" in disk.keys() else "vim_id"
        if disk.get(key_id):
            block_device_mapping["vd" + chr(base_disk_index)] = disk[key_id]
            existing_vim_volumes.append({"id": disk[key_id]})
        else:
            # Create persistent root volume
            volume = self.cinder.volumes.create(
                size=disk["size"],
                name=name + "vd" + chr(base_disk_index),
                imageRef=disk["image_id"],
                # Make sure volume is in the same AZ as the VM to be attached to
                availability_zone=storage_av_zone,
            )
            boot_volume_id = volume.id
            self.update_block_device_mapping(
                volume=volume,
                block_device_mapping=block_device_mapping,
                base_disk_index=base_disk_index,
                disk=disk,
                created_items=created_items,
            )

            return boot_volume_id

    @staticmethod
    def update_block_device_mapping(
        volume: object,
        block_device_mapping: dict,
        base_disk_index: int,
        disk: dict,
        created_items: dict,
    ) -> None:
        """Add volume information to block device mapping dict.
        Args:
            volume  (object):                   Created volume object
            block_device_mapping    (dict):     Block device details
            base_disk_index (int):              Disk index
            disk    (dict):                     Disk details
            created_items   (dict):             All created items belongs to VM
        """
        if not volume:
            raise vimconn.VimConnException("Volume is empty.")

        if not hasattr(volume, "id"):
            raise vimconn.VimConnException(
                "Created volume is not valid, does not have id attribute."
            )

        block_device_mapping["vd" + chr(base_disk_index)] = volume.id
        if disk.get("multiattach"):  # multiattach volumes do not belong to VDUs
            return
        volume_txt = "volume:" + str(volume.id)
        if disk.get("keep"):
            volume_txt += ":keep"
        created_items[volume_txt] = True

    @catch_any_exception
    def new_shared_volumes(self, shared_volume_data) -> (str, str):
        self.logger.debug("Creating new shared volume")
        availability_zone = (
            self.storage_availability_zone
            if self.storage_availability_zone
            else self.vm_av_zone
        )
        volume = self.cinder.volumes.create(
            size=shared_volume_data["size"],
            name=shared_volume_data["name"],
            volume_type="multiattach",
            availability_zone=availability_zone,
        )
        return volume.name, volume.id

    def _prepare_shared_volumes(
        self,
        name: str,
        disk: dict,
        base_disk_index: int,
        block_device_mapping: dict,
        existing_vim_volumes: list,
        created_items: dict,
    ):
        self.logger.debug("Preparing shared volumes")
        volumes = {volume.name: volume.id for volume in self.cinder.volumes.list()}
        if volumes.get(disk["name"]):
            sv_id = volumes[disk["name"]]
            max_retries = 3
            vol_status = ""
            # If this is not the first VM to attach the volume, volume status may be "reserved" for a short time
            while max_retries:
                max_retries -= 1
                volume = self.cinder.volumes.get(sv_id)
                vol_status = volume.status
                if volume.status not in ("in-use", "available"):
                    time.sleep(5)
                    continue
                self.update_block_device_mapping(
                    volume=volume,
                    block_device_mapping=block_device_mapping,
                    base_disk_index=base_disk_index,
                    disk=disk,
                    created_items=created_items,
                )
                return
            raise vimconn.VimConnException(
                "Shared volume is not prepared, status is: {}".format(vol_status),
                http_code=vimconn.HTTP_Internal_Server_Error,
            )

    def _prepare_non_root_persistent_volumes(
        self,
        name: str,
        disk: dict,
        storage_av_zone: list,
        block_device_mapping: dict,
        base_disk_index: int,
        existing_vim_volumes: list,
        created_items: dict,
    ) -> None:
        """Prepare persistent volumes for new VM instance.

        Args:
            name    (str):                      Name of VM instance
            disk    (dict):                     Disk details
            storage_av_zone  (list):            Storage of availability zones
            block_device_mapping    (dict):     Block device details
            base_disk_index (int):              Disk index
            existing_vim_volumes    (list):     Existing disk details
            created_items   (dict):             All created items belongs to VM
        """
        # Non-root persistent volumes
        # Disk may include only vim_volume_id or only vim_id."
        self.logger.debug("Preparing non-root persistent volumes")
        key_id = "vim_volume_id" if "vim_volume_id" in disk.keys() else "vim_id"
        if disk.get(key_id):
            # Use existing persistent volume
            block_device_mapping["vd" + chr(base_disk_index)] = disk[key_id]
            existing_vim_volumes.append({"id": disk[key_id]})
        else:
            volume_name = f"{name}vd{chr(base_disk_index)}"
            volume = self.cinder.volumes.create(
                size=disk["size"],
                name=volume_name,
                # Make sure volume is in the same AZ as the VM to be attached to
                availability_zone=storage_av_zone,
            )
            self.update_block_device_mapping(
                volume=volume,
                block_device_mapping=block_device_mapping,
                base_disk_index=base_disk_index,
                disk=disk,
                created_items=created_items,
            )

    def _wait_for_created_volumes_availability(
        self, elapsed_time: int, created_items: dict
    ) -> Optional[int]:
        """Wait till created volumes become available.

        Args:
            elapsed_time    (int):          Passed time while waiting
            created_items   (dict):         All created items belongs to VM

        Returns:
            elapsed_time    (int):          Time spent while waiting

        """
        self.logger.debug("Waiting for all created volumes to become available")
        while elapsed_time < volume_timeout:
            self.logger.debug("Checking disk availability for created volumes")
            for created_item in created_items:
                v, volume_id = (
                    created_item.split(":")[0],
                    created_item.split(":")[1],
                )
                if v == "volume":
                    self.logger.debug(f"Checking volume: {volume_id}")
                    volume = self.cinder.volumes.get(volume_id)
                    if (
                        volume.volume_type == "multiattach"
                        and volume.status == "in-use"
                    ):
                        return elapsed_time
                    elif volume.status != "available":
                        break
            else:
                # All ready: break from while
                break

            time.sleep(5)
            elapsed_time += 5

        return elapsed_time

    def _wait_for_existing_volumes_availability(
        self, elapsed_time: int, existing_vim_volumes: list
    ) -> Optional[int]:
        """Wait till existing volumes become available.

        Args:
            elapsed_time    (int):          Passed time while waiting
            existing_vim_volumes   (list):  Existing volume details

        Returns:
            elapsed_time    (int):          Time spent while waiting

        """

        self.logger.debug("Waiting for all existing volumes to become available")
        while elapsed_time < volume_timeout:
            self.logger.debug("Checking disk availability for existing volumes")
            for volume in existing_vim_volumes:
                self.logger.debug(f"Checking existing volume: {volume}")
                v = self.cinder.volumes.get(volume["id"])
                if v.volume_type == "multiattach" and v.status == "in-use":
                    return elapsed_time
                elif v.status != "available":
                    break
            else:  # all ready: break from while
                break

            time.sleep(5)
            elapsed_time += 5

        return elapsed_time

    def _prepare_disk_for_vminstance(
        self,
        name: str,
        existing_vim_volumes: list,
        created_items: dict,
        storage_av_zone: list,
        block_device_mapping: dict,
        disk_list: list = None,
    ) -> None:
        """Prepare all volumes for new VM instance.

        Args:
            name    (str):                      Name of Instance
            existing_vim_volumes    (list):     List of existing volumes
            created_items   (dict):             All created items belongs to VM
            storage_av_zone  (list):            Storage availability zone
            block_device_mapping (dict):        Block devices to be attached to VM
            disk_list   (list):                 List of disks

        """
        # Create additional volumes in case these are present in disk_list
        self.logger.debug("Preparing disks for VM instances")
        base_disk_index = ord("b")
        boot_volume_id = None
        elapsed_time = 0
        for disk in disk_list:
            self.logger.debug(f"Disk: {disk}")
            if "image_id" in disk:
                # Root persistent volume
                base_disk_index = ord("a")
                boot_volume_id = self._prepare_persistent_root_volumes(
                    name=name,
                    storage_av_zone=storage_av_zone,
                    disk=disk,
                    base_disk_index=base_disk_index,
                    block_device_mapping=block_device_mapping,
                    existing_vim_volumes=existing_vim_volumes,
                    created_items=created_items,
                )
            elif disk.get("multiattach"):
                self._prepare_shared_volumes(
                    name=name,
                    disk=disk,
                    base_disk_index=base_disk_index,
                    block_device_mapping=block_device_mapping,
                    existing_vim_volumes=existing_vim_volumes,
                    created_items=created_items,
                )
            else:
                # Non-root persistent volume
                self._prepare_non_root_persistent_volumes(
                    name=name,
                    disk=disk,
                    storage_av_zone=storage_av_zone,
                    block_device_mapping=block_device_mapping,
                    base_disk_index=base_disk_index,
                    existing_vim_volumes=existing_vim_volumes,
                    created_items=created_items,
                )
            base_disk_index += 1

        # Wait until created volumes are with status available
        elapsed_time = self._wait_for_created_volumes_availability(
            elapsed_time, created_items
        )
        # Wait until existing volumes in vim are with status available
        elapsed_time = self._wait_for_existing_volumes_availability(
            elapsed_time, existing_vim_volumes
        )
        # If we exceeded the timeout rollback
        if elapsed_time >= volume_timeout:
            raise vimconn.VimConnException(
                "Timeout creating volumes for instance " + name,
                http_code=vimconn.HTTP_Request_Timeout,
            )
        if boot_volume_id:
            self.cinder.volumes.set_bootable(boot_volume_id, True)

    def _find_the_external_network_for_floating_ip(self):
        """Get the external network ip in order to create floating IP.

        Returns:
            pool_id (str):      External network pool ID

        """

        # Find the external network
        external_nets = list()

        for net in self.neutron.list_networks()["networks"]:
            if net["router:external"]:
                external_nets.append(net)

        if len(external_nets) == 0:
            raise vimconn.VimConnException(
                "Cannot create floating_ip automatically since "
                "no external network is present",
                http_code=vimconn.HTTP_Conflict,
            )

        if len(external_nets) > 1:
            raise vimconn.VimConnException(
                "Cannot create floating_ip automatically since "
                "multiple external networks are present",
                http_code=vimconn.HTTP_Conflict,
            )

        # Pool ID
        return external_nets[0].get("id")

    def _neutron_create_float_ip(self, param: dict, created_items: dict) -> None:
        """Trigger neutron to create a new floating IP using external network ID.

        Args:
            param   (dict):             Input parameters to create a floating IP
            created_items   (dict):     All created items belongs to new VM instance

        Raises:

            VimConnException
        """
        try:
            self.logger.debug("Creating floating IP")
            new_floating_ip = self.neutron.create_floatingip(param)
            free_floating_ip = new_floating_ip["floatingip"]["id"]
            created_items["floating_ip:" + str(free_floating_ip)] = True

        except Exception as e:
            raise vimconn.VimConnException(
                type(e).__name__ + ": Cannot create new floating_ip " + str(e),
                http_code=vimconn.HTTP_Conflict,
            )

    def _create_floating_ip(
        self, floating_network: dict, server: object, created_items: dict
    ) -> None:
        """Get the available Pool ID and create a new floating IP.

        Args:
            floating_network    (dict):         Dict including external network ID
            server   (object):                  Server object
            created_items   (dict):             All created items belongs to new VM instance

        """

        # Pool_id is available
        if (
            isinstance(floating_network["floating_ip"], str)
            and floating_network["floating_ip"].lower() != "true"
        ):
            pool_id = floating_network["floating_ip"]

        # Find the Pool_id
        else:
            pool_id = self._find_the_external_network_for_floating_ip()

        param = {
            "floatingip": {
                "floating_network_id": pool_id,
                "tenant_id": server.tenant_id,
            }
        }

        self._neutron_create_float_ip(param, created_items)

    def _find_floating_ip(
        self,
        server: object,
        floating_ips: list,
        floating_network: dict,
    ) -> Optional[str]:
        """Find the available free floating IPs if there are.

        Args:
            server  (object):                   Server object
            floating_ips    (list):             List of floating IPs
            floating_network    (dict):         Details of floating network such as ID

        Returns:
            free_floating_ip    (str):          Free floating ip address

        """
        for fip in floating_ips:
            if fip.get("port_id") or fip.get("tenant_id") != server.tenant_id:
                continue

            if isinstance(floating_network["floating_ip"], str):
                if fip.get("floating_network_id") != floating_network["floating_ip"]:
                    continue

            return fip["id"]

    def _assign_floating_ip(
        self, free_floating_ip: str, floating_network: dict
    ) -> Dict:
        """Assign the free floating ip address to port.

        Args:
            free_floating_ip    (str):          Floating IP to be assigned
            floating_network    (dict):         ID of floating network

        Returns:
            fip (dict)          (dict):         Floating ip details

        """
        # The vim_id key contains the neutron.port_id
        self.neutron.update_floatingip(
            free_floating_ip,
            {"floatingip": {"port_id": floating_network["vim_id"]}},
        )
        # For race condition ensure not re-assigned to other VM after 5 seconds
        time.sleep(5)

        return self.neutron.show_floatingip(free_floating_ip)

    def _get_free_floating_ip(
        self, server: object, floating_network: dict
    ) -> Optional[str]:
        """Get the free floating IP address.

        Args:
            server  (object):               Server Object
            floating_network    (dict):     Floating network details

        Returns:
            free_floating_ip    (str):      Free floating ip addr

        """

        floating_ips = self.neutron.list_floatingips().get("floatingips", ())

        # Randomize
        random.shuffle(floating_ips)

        return self._find_floating_ip(server, floating_ips, floating_network)

    def _prepare_external_network_for_vminstance(
        self,
        external_network: list,
        server: object,
        created_items: dict,
        vm_start_time: float,
    ) -> None:
        """Assign floating IP address for VM instance.

        Args:
            external_network    (list):         ID of External network
            server  (object):                   Server Object
            created_items   (dict):             All created items belongs to new VM instance
            vm_start_time   (float):            Time as a floating point number expressed in seconds since the epoch, in UTC

        Raises:
            VimConnException

        """
        for floating_network in external_network:
            try:
                assigned = False
                floating_ip_retries = 3
                # In case of RO in HA there can be conflicts, two RO trying to assign same floating IP, so retry
                # several times
                while not assigned:
                    free_floating_ip = self._get_free_floating_ip(
                        server, floating_network
                    )

                    if not free_floating_ip:
                        self._create_floating_ip(
                            floating_network, server, created_items
                        )

                    try:
                        # For race condition ensure not already assigned
                        fip = self.neutron.show_floatingip(free_floating_ip)

                        if fip["floatingip"].get("port_id"):
                            continue

                        # Assign floating ip
                        fip = self._assign_floating_ip(
                            free_floating_ip, floating_network
                        )

                        if fip["floatingip"]["port_id"] != floating_network["vim_id"]:
                            self.logger.warning(
                                "floating_ip {} re-assigned to other port".format(
                                    free_floating_ip
                                )
                            )
                            continue

                        self.logger.debug(
                            "Assigned floating_ip {} to VM {}".format(
                                free_floating_ip, server.id
                            )
                        )

                        assigned = True

                    except Exception as e:
                        # Openstack need some time after VM creation to assign an IP. So retry if fails
                        vm_status = self.nova.servers.get(server.id).status

                        if vm_status not in ("ACTIVE", "ERROR"):
                            if time.time() - vm_start_time < server_timeout:
                                time.sleep(5)
                                continue
                        elif floating_ip_retries > 0:
                            floating_ip_retries -= 1
                            continue

                        raise vimconn.VimConnException(
                            "Cannot create floating_ip: {} {}".format(
                                type(e).__name__, e
                            ),
                            http_code=vimconn.HTTP_Conflict,
                        )

            except Exception as e:
                if not floating_network["exit_on_floating_ip_error"]:
                    self.logger.error("Cannot create floating_ip. %s", str(e))
                    continue

                raise

    def _update_port_security_for_vminstance(
        self,
        no_secured_ports: list,
        server: object,
    ) -> None:
        """Updates the port security according to no_secured_ports list.

        Args:
            no_secured_ports    (list):     List of ports that security will be disabled
            server  (object):               Server Object

        Raises:
            VimConnException

        """
        # Wait until the VM is active and then disable the port-security
        if no_secured_ports:
            self.__wait_for_vm(server.id, "ACTIVE")

        for port in no_secured_ports:
            port_update = {
                "port": {"port_security_enabled": False, "security_groups": None}
            }

            if port[1] == "allow-address-pairs":
                port_update = {
                    "port": {"allowed_address_pairs": [{"ip_address": "0.0.0.0/0"}]}
                }

            try:
                self.neutron.update_port(port[0], port_update)

            except Exception:
                raise vimconn.VimConnException(
                    "It was not possible to disable port security for port {}".format(
                        port[0]
                    )
                )

    def new_vminstance(
        self,
        name: str,
        description: str,
        start: bool,
        image_id: str,
        flavor_id: str,
        affinity_group_list: list,
        net_list: list,
        cloud_config=None,
        disk_list=None,
        availability_zone_index=None,
        availability_zone_list=None,
        security_group_name=None,
    ) -> tuple:
        """Adds a VM instance to VIM.

        Args:
            name    (str):          name of VM
            description (str):      description
            start   (bool):         indicates if VM must start or boot in pause mode. Ignored
            image_id    (str)       image uuid
            flavor_id   (str)       flavor uuid
            affinity_group_list (list):     list of affinity groups, each one is a dictionary.Ignore if empty.
            net_list    (list):         list of interfaces, each one is a dictionary with:
                name:   name of network
                net_id:     network uuid to connect
                vpci:   virtual vcpi to assign, ignored because openstack lack #TODO
                model:  interface model, ignored #TODO
                mac_address:    used for  SR-IOV ifaces #TODO for other types
                use:    'data', 'bridge',  'mgmt'
                type:   'virtual', 'PCI-PASSTHROUGH'('PF'), 'SR-IOV'('VF'), 'VFnotShared'
                vim_id:     filled/added by this function
                floating_ip:    True/False (or it can be None)
                port_security:  True/False
            cloud_config    (dict): (optional) dictionary with:
                key-pairs:      (optional) list of strings with the public key to be inserted to the default user
                users:      (optional) list of users to be inserted, each item is a dict with:
                    name:   (mandatory) user name,
                    key-pairs: (optional) list of strings with the public key to be inserted to the user
                user-data:  (optional) string is a text script to be passed directly to cloud-init
                config-files:   (optional). List of files to be transferred. Each item is a dict with:
                    dest:   (mandatory) string with the destination absolute path
                    encoding:   (optional, by default text). Can be one of:
                        'b64', 'base64', 'gz', 'gz+b64', 'gz+base64', 'gzip+b64', 'gzip+base64'
                    content :    (mandatory) string with the content of the file
                    permissions:    (optional) string with file permissions, typically octal notation '0644'
                    owner:  (optional) file owner, string with the format 'owner:group'
                boot-data-drive:    boolean to indicate if user-data must be passed using a boot drive (hard disk)
            disk_list:  (optional) list with additional disks to the VM. Each item is a dict with:
                image_id:   (optional). VIM id of an existing image. If not provided an empty disk must be mounted
                size:   (mandatory) string with the size of the disk in GB
                vim_id:  (optional) should use this existing volume id
            availability_zone_index:    Index of availability_zone_list to use for this this VM. None if not AV required
            availability_zone_list:     list of availability zones given by user in the VNFD descriptor.  Ignore if
                availability_zone_index is None
                #TODO ip, security groups

        Returns:
            A tuple with the instance identifier and created_items or raises an exception on error
            created_items can be None or a dictionary where this method can include key-values that will be passed to
            the method delete_vminstance and action_vminstance. Can be used to store created ports, volumes, etc.
            Format is vimconnector dependent, but do not use nested dictionaries and a value of None should be the same
            as not present.

        """
        self.logger.debug(
            "new_vminstance input: image='%s' flavor='%s' nics='%s'",
            image_id,
            flavor_id,
            str(net_list),
        )
        server = None
        created_items = {}
        net_list_vim = []
        # list of external networks to be connected to instance, later on used to create floating_ip
        external_network = []
        # List of ports with port-security disabled
        no_secured_ports = []
        block_device_mapping = {}
        existing_vim_volumes = []
        server_group_id = None
        scheduller_hints = {}

        try:
            # Check the Openstack Connection
            self._reload_connection()

            # Prepare network list
            self._prepare_network_for_vminstance(
                name=name,
                net_list=net_list,
                created_items=created_items,
                net_list_vim=net_list_vim,
                external_network=external_network,
                no_secured_ports=no_secured_ports,
                security_group_name=security_group_name,
            )

            # Cloud config
            config_drive, userdata = self._create_user_data(cloud_config)

            # Get availability Zone
            self.vm_av_zone = self._get_vm_availability_zone(
                availability_zone_index, availability_zone_list
            )

            storage_av_zone = (
                self.storage_availability_zone
                if self.storage_availability_zone
                else self.vm_av_zone
            )

            if disk_list:
                # Prepare disks
                self._prepare_disk_for_vminstance(
                    name=name,
                    existing_vim_volumes=existing_vim_volumes,
                    created_items=created_items,
                    storage_av_zone=storage_av_zone,
                    block_device_mapping=block_device_mapping,
                    disk_list=disk_list,
                )

            if affinity_group_list:
                # Only first id on the list will be used. Openstack restriction
                server_group_id = affinity_group_list[0]["affinity_group_id"]
                scheduller_hints["group"] = server_group_id

            self.logger.debug(
                "nova.servers.create({}, {}, {}, nics={}, security_groups={}, "
                "availability_zone={}, key_name={}, userdata={}, config_drive={}, "
                "block_device_mapping={}, server_group={})".format(
                    name,
                    image_id,
                    flavor_id,
                    net_list_vim,
                    self.config.get("security_groups"),
                    self.vm_av_zone,
                    self.config.get("keypair"),
                    userdata,
                    config_drive,
                    block_device_mapping,
                    server_group_id,
                )
            )
            # Create VM
            server = self.nova.servers.create(
                name=name,
                image=image_id,
                flavor=flavor_id,
                nics=net_list_vim,
                security_groups=self.config.get("security_groups"),
                # TODO remove security_groups in future versions. Already at neutron port
                availability_zone=self.vm_av_zone,
                key_name=self.config.get("keypair"),
                userdata=userdata,
                config_drive=config_drive,
                block_device_mapping=block_device_mapping,
                scheduler_hints=scheduller_hints,
            )

            vm_start_time = time.time()

            self._update_port_security_for_vminstance(no_secured_ports, server)

            self._prepare_external_network_for_vminstance(
                external_network=external_network,
                server=server,
                created_items=created_items,
                vm_start_time=vm_start_time,
            )

            return server.id, created_items

        except Exception as e:
            server_id = None
            if server:
                server_id = server.id

            try:
                created_items = self.remove_keep_tag_from_persistent_volumes(
                    created_items
                )

                self.delete_vminstance(server_id, created_items)

            except Exception as e2:
                self.logger.error("new_vminstance rollback fail {}".format(e2))

            self._format_exception(e)

    @staticmethod
    def remove_keep_tag_from_persistent_volumes(created_items: Dict) -> Dict:
        """Removes the keep flag from persistent volumes. So, those volumes could be removed.

        Args:
            created_items (dict):       All created items belongs to VM

        Returns:
            updated_created_items   (dict):     Dict which does not include keep flag for volumes.

        """
        return {
            key.replace(":keep", ""): value for (key, value) in created_items.items()
        }

    def get_vminstance(self, vm_id):
        """Returns the VM instance information from VIM"""
        return self._find_nova_server(vm_id)

    @catch_any_exception
    def get_vminstance_console(self, vm_id, console_type="vnc"):
        """
        Get a console for the virtual machine
        Params:
            vm_id: uuid of the VM
            console_type, can be:
                "novnc" (by default), "xvpvnc" for VNC types,
                "rdp-html5" for RDP types, "spice-html5" for SPICE types
        Returns dict with the console parameters:
                protocol: ssh, ftp, http, https, ...
                server:   usually ip address
                port:     the http, ssh, ... port
                suffix:   extra text, e.g. the http path and query string
        """
        self.logger.debug("Getting VM CONSOLE from VIM")
        self._reload_connection()
        server = self.nova.servers.find(id=vm_id)

        if console_type is None or console_type == "novnc":
            console_dict = server.get_vnc_console("novnc")
        elif console_type == "xvpvnc":
            console_dict = server.get_vnc_console(console_type)
        elif console_type == "rdp-html5":
            console_dict = server.get_rdp_console(console_type)
        elif console_type == "spice-html5":
            console_dict = server.get_spice_console(console_type)
        else:
            raise vimconn.VimConnException(
                "console type '{}' not allowed".format(console_type),
                http_code=vimconn.HTTP_Bad_Request,
            )

        console_dict1 = console_dict.get("console")

        if console_dict1:
            console_url = console_dict1.get("url")

            if console_url:
                # parse console_url
                protocol_index = console_url.find("//")
                suffix_index = (
                    console_url[protocol_index + 2 :].find("/") + protocol_index + 2
                )
                port_index = (
                    console_url[protocol_index + 2 : suffix_index].find(":")
                    + protocol_index
                    + 2
                )

                if protocol_index < 0 or port_index < 0 or suffix_index < 0:
                    return (
                        -vimconn.HTTP_Internal_Server_Error,
                        "Unexpected response from VIM",
                    )

                console_dict = {
                    "protocol": console_url[0:protocol_index],
                    "server": console_url[protocol_index + 2 : port_index],
                    "port": console_url[port_index:suffix_index],
                    "suffix": console_url[suffix_index + 1 :],
                }
                protocol_index += 2

                return console_dict
        raise vimconn.VimConnUnexpectedResponse("Unexpected response from VIM")

    def _delete_ports_by_id_wth_neutron(self, k_id: str) -> None:
        """Neutron delete ports by id.
        Args:
            k_id    (str):      Port id in the VIM
        """
        try:
            self.neutron.delete_port(k_id)

        except (neExceptions.ConnectionFailed, ConnectionError) as e:
            self.logger.error("Error deleting port: {}: {}".format(type(e).__name__, e))
            # If there is connection error, raise.
            self._format_exception(e)
        except Exception as e:
            self.logger.error("Error deleting port: {}: {}".format(type(e).__name__, e))

    def delete_shared_volumes(self, shared_volume_vim_id: str) -> bool:
        """Cinder delete volume by id.
        Args:
            shared_volume_vim_id    (str):                  ID of shared volume in VIM
        """
        elapsed_time = 0
        try:
            while elapsed_time < server_timeout:
                vol_status = self.cinder.volumes.get(shared_volume_vim_id).status
                if vol_status == "available":
                    self.cinder.volumes.delete(shared_volume_vim_id)
                    return True

                time.sleep(5)
                elapsed_time += 5

            if elapsed_time >= server_timeout:
                raise vimconn.VimConnException(
                    "Timeout waiting for volume "
                    + shared_volume_vim_id
                    + " to be available",
                    http_code=vimconn.HTTP_Request_Timeout,
                )

        except Exception as e:
            self.logger.error(
                "Error deleting volume: {}: {}".format(type(e).__name__, e)
            )
            self._format_exception(e)

    def _delete_volumes_by_id_wth_cinder(
        self, k: str, k_id: str, volumes_to_hold: list, created_items: dict
    ) -> bool:
        """Cinder delete volume by id.
        Args:
            k   (str):                      Full item name in created_items
            k_id    (str):                  ID of floating ip in VIM
            volumes_to_hold (list):          Volumes not to delete
            created_items   (dict):         All created items belongs to VM
        """
        try:
            if k_id in volumes_to_hold:
                return False

            if self.cinder.volumes.get(k_id).status != "available":
                return True

            else:
                self.cinder.volumes.delete(k_id)
                created_items[k] = None

        except (cExceptions.ConnectionError, ConnectionError) as e:
            self.logger.error(
                "Error deleting volume: {}: {}".format(type(e).__name__, e)
            )
            self._format_exception(e)
        except Exception as e:
            self.logger.error(
                "Error deleting volume: {}: {}".format(type(e).__name__, e)
            )

    def _delete_floating_ip_by_id(self, k: str, k_id: str, created_items: dict) -> None:
        """Neutron delete floating ip by id.
        Args:
            k   (str):                      Full item name in created_items
            k_id    (str):                  ID of floating ip in VIM
            created_items   (dict):         All created items belongs to VM
        """
        try:
            self.neutron.delete_floatingip(k_id)
            created_items[k] = None

        except (neExceptions.ConnectionFailed, ConnectionError) as e:
            self.logger.error(
                "Error deleting floating ip: {}: {}".format(type(e).__name__, e)
            )
            self._format_exception(e)
        except Exception as e:
            self.logger.error(
                "Error deleting floating ip: {}: {}".format(type(e).__name__, e)
            )

    @staticmethod
    def _get_item_name_id(k: str) -> Tuple[str, str]:
        k_item, _, k_id = k.partition(":")
        return k_item, k_id

    def _delete_vm_ports_attached_to_network(self, created_items: dict) -> None:
        """Delete VM ports attached to the networks before deleting virtual machine.
        Args:
            created_items   (dict):     All created items belongs to VM
        """

        for k, v in created_items.items():
            if not v:  # skip already deleted
                continue

            try:
                k_item, k_id = self._get_item_name_id(k)
                if k_item == "port":
                    self._delete_ports_by_id_wth_neutron(k_id)

            except (neExceptions.ConnectionFailed, ConnectionError) as e:
                self.logger.error(
                    "Error deleting port: {}: {}".format(type(e).__name__, e)
                )
                self._format_exception(e)
            except Exception as e:
                self.logger.error(
                    "Error deleting port: {}: {}".format(type(e).__name__, e)
                )

    def _delete_created_items(
        self, created_items: dict, volumes_to_hold: list, keep_waiting: bool
    ) -> bool:
        """Delete Volumes and floating ip if they exist in created_items."""
        for k, v in created_items.items():
            if not v:  # skip already deleted
                continue

            try:
                k_item, k_id = self._get_item_name_id(k)
                if k_item == "volume":
                    unavailable_vol = self._delete_volumes_by_id_wth_cinder(
                        k, k_id, volumes_to_hold, created_items
                    )

                    if unavailable_vol:
                        keep_waiting = True

                elif k_item == "floating_ip":
                    self._delete_floating_ip_by_id(k, k_id, created_items)

            except (
                cExceptions.ConnectionError,
                neExceptions.ConnectionFailed,
                ConnectionError,
                AttributeError,
                TypeError,
            ) as e:
                self.logger.error("Error deleting {}: {}".format(k, e))
                self._format_exception(e)

            except Exception as e:
                self.logger.error("Error deleting {}: {}".format(k, e))

        return keep_waiting

    @staticmethod
    def _extract_items_wth_keep_flag_from_created_items(created_items: dict) -> dict:
        """Remove the volumes which has key flag from created_items

        Args:
            created_items   (dict):         All created items belongs to VM

        Returns:
            created_items   (dict):         Persistent volumes eliminated created_items
        """
        return {
            key: value
            for (key, value) in created_items.items()
            if len(key.split(":")) == 2
        }

    @catch_any_exception
    def delete_vminstance(
        self, vm_id: str, created_items: dict = None, volumes_to_hold: list = None
    ) -> None:
        """Removes a VM instance from VIM. Returns the old identifier.
        Args:
            vm_id   (str):              Identifier of VM instance
            created_items   (dict):     All created items belongs to VM
            volumes_to_hold (list):     Volumes_to_hold
        """
        if created_items is None:
            created_items = {}
        if volumes_to_hold is None:
            volumes_to_hold = []

        try:
            created_items = self._extract_items_wth_keep_flag_from_created_items(
                created_items
            )

            self._reload_connection()

            # Delete VM ports attached to the networks before the virtual machine
            if created_items:
                self._delete_vm_ports_attached_to_network(created_items)

            if vm_id:
                self.nova.servers.delete(vm_id)

            # Although having detached, volumes should have in active status before deleting.
            # We ensure in this loop
            keep_waiting = True
            elapsed_time = 0

            while keep_waiting and elapsed_time < volume_timeout:
                keep_waiting = False

                # Delete volumes and floating IP.
                keep_waiting = self._delete_created_items(
                    created_items, volumes_to_hold, keep_waiting
                )

                if keep_waiting:
                    time.sleep(1)
                    elapsed_time += 1
        except (nvExceptions.NotFound, nvExceptions.ResourceNotFound) as e:
            # If VM does not exist, it does not raise
            self.logger.warning(f"Error deleting VM: {vm_id} is not found, {str(e)}")

    def refresh_vms_status(self, vm_list):
        """Get the status of the virtual machines and their interfaces/ports
        Params: the list of VM identifiers
        Returns a dictionary with:
            vm_id:          #VIM id of this Virtual Machine
                status:     #Mandatory. Text with one of:
                            #  DELETED (not found at vim)
                            #  VIM_ERROR (Cannot connect to VIM, VIM response error, ...)
                            #  OTHER (Vim reported other status not understood)
                            #  ERROR (VIM indicates an ERROR status)
                            #  ACTIVE, PAUSED, SUSPENDED, INACTIVE (not running),
                            #  CREATING (on building process), ERROR
                            #  ACTIVE:NoMgmtIP (Active but any of its interface has an IP address
                            #
                error_msg:  #Text with VIM error message, if any. Or the VIM connection ERROR
                vim_info:   #Text with plain information obtained from vim (yaml.safe_dump)
                interfaces:
                 -  vim_info:         #Text with plain information obtained from vim (yaml.safe_dump)
                    mac_address:      #Text format XX:XX:XX:XX:XX:XX
                    vim_net_id:       #network id where this interface is connected
                    vim_interface_id: #interface/port VIM id
                    ip_address:       #null, or text with IPv4, IPv6 address
                    compute_node:     #identification of compute node where PF,VF interface is allocated
                    pci:              #PCI address of the NIC that hosts the PF,VF
                    vlan:             #physical VLAN used for VF
        """
        vm_dict = {}
        self.logger.debug(
            "refresh_vms status: Getting tenant VM instance information from VIM"
        )
        for vm_id in vm_list:
            vm = {}

            try:
                vm_vim = self.get_vminstance(vm_id)

                if vm_vim["status"] in vmStatus2manoFormat:
                    vm["status"] = vmStatus2manoFormat[vm_vim["status"]]
                else:
                    vm["status"] = "OTHER"
                    vm["error_msg"] = "VIM status reported " + vm_vim["status"]

                vm_vim.pop("OS-EXT-SRV-ATTR:user_data", None)
                vm_vim.pop("user_data", None)
                vm["vim_info"] = self.serialize(vm_vim)

                vm["interfaces"] = []
                if vm_vim.get("fault"):
                    vm["error_msg"] = str(vm_vim["fault"])

                # get interfaces
                try:
                    self._reload_connection()
                    port_dict = self.neutron.list_ports(device_id=vm_id)

                    for port in port_dict["ports"]:
                        interface = {}
                        interface["vim_info"] = self.serialize(port)
                        interface["mac_address"] = port.get("mac_address")
                        interface["vim_net_id"] = port["network_id"]
                        interface["vim_interface_id"] = port["id"]
                        # check if OS-EXT-SRV-ATTR:host is there,
                        # in case of non-admin credentials, it will be missing

                        if vm_vim.get("OS-EXT-SRV-ATTR:host"):
                            interface["compute_node"] = vm_vim["OS-EXT-SRV-ATTR:host"]

                        interface["pci"] = None

                        # check if binding:profile is there,
                        # in case of non-admin credentials, it will be missing
                        if port.get("binding:profile"):
                            if port["binding:profile"].get("pci_slot"):
                                # TODO: At the moment sr-iov pci addresses are converted to PF pci addresses by setting
                                #  the slot to 0x00
                                # TODO: This is just a workaround valid for niantinc. Find a better way to do so
                                #   CHANGE DDDD:BB:SS.F to DDDD:BB:00.(F%2)   assuming there are 2 ports per nic
                                pci = port["binding:profile"]["pci_slot"]
                                # interface["pci"] = pci[:-4] + "00." + str(int(pci[-1]) % 2)
                                interface["pci"] = pci

                        interface["vlan"] = None

                        if port.get("binding:vif_details"):
                            interface["vlan"] = port["binding:vif_details"].get("vlan")

                        # Get vlan from network in case not present in port for those old openstacks and cases where
                        # it is needed vlan at PT
                        if not interface["vlan"]:
                            # if network is of type vlan and port is of type direct (sr-iov) then set vlan id
                            network = self.neutron.show_network(port["network_id"])

                            if (
                                network["network"].get("provider:network_type")
                                == "vlan"
                            ):
                                # and port.get("binding:vnic_type") in ("direct", "direct-physical"):
                                interface["vlan"] = network["network"].get(
                                    "provider:segmentation_id"
                                )

                        ips = []
                        # look for floating ip address
                        try:
                            floating_ip_dict = self.neutron.list_floatingips(
                                port_id=port["id"]
                            )

                            if floating_ip_dict.get("floatingips"):
                                ips.append(
                                    floating_ip_dict["floatingips"][0].get(
                                        "floating_ip_address"
                                    )
                                )
                        except Exception:
                            pass

                        for subnet in port["fixed_ips"]:
                            ips.append(subnet["ip_address"])

                        interface["ip_address"] = ";".join(ips)
                        vm["interfaces"].append(interface)
                except Exception as e:
                    self.logger.error(
                        "Error getting vm interface information {}: {}".format(
                            type(e).__name__, e
                        ),
                        exc_info=True,
                    )
            except vimconn.VimConnNotFoundException as e:
                self.logger.error("Exception getting vm status: %s", str(e))
                vm["status"] = "DELETED"
                vm["error_msg"] = str(e)
            except vimconn.VimConnException as e:
                self.logger.error("Exception getting vm status: %s", str(e))
                vm["status"] = "VIM_ERROR"
                vm["error_msg"] = str(e)

            vm_dict[vm_id] = vm

        return vm_dict

    @catch_any_exception
    def action_vminstance(self, vm_id, action_dict, created_items={}):
        """Send and action over a VM instance from VIM
        Returns None or the console dict if the action was successfully sent to the VIM
        """
        self.logger.debug("Action over VM '%s': %s", vm_id, str(action_dict))
        self._reload_connection()
        server = self.nova.servers.find(id=vm_id)
        if "start" in action_dict:
            if action_dict["start"] == "rebuild":
                server.rebuild()
                vm_state = self.__wait_for_vm(vm_id, "ACTIVE")
                if not vm_state:
                    raise nvExceptions.BadRequest(
                        409,
                        message="Cannot 'REBUILD' vm_state is in ERROR",
                    )
            else:
                if server.status == "PAUSED":
                    server.unpause()
                elif server.status == "SUSPENDED":
                    server.resume()
                elif server.status == "SHUTOFF":
                    server.start()
                    vm_state = self.__wait_for_vm(vm_id, "ACTIVE")
                    if not vm_state:
                        raise nvExceptions.BadRequest(
                            409,
                            message="Cannot 'START' vm_state is in ERROR",
                        )
                else:
                    self.logger.debug(
                        "ERROR : Instance is not in SHUTOFF/PAUSE/SUSPEND state"
                    )
                    raise vimconn.VimConnException(
                        "Cannot 'start' instance while it is in active state",
                        http_code=vimconn.HTTP_Bad_Request,
                    )
        elif "pause" in action_dict:
            server.pause()
        elif "resume" in action_dict:
            server.resume()
        elif "shutoff" in action_dict or "shutdown" in action_dict:
            self.logger.debug("server status %s", server.status)
            if server.status == "ACTIVE":
                server.stop()
                vm_state = self.__wait_for_vm(vm_id, "SHUTOFF")
                if not vm_state:
                    raise nvExceptions.BadRequest(
                        409,
                        message="Cannot 'STOP' vm_state is in ERROR",
                    )
            else:
                self.logger.debug("ERROR: VM is not in Active state")
                raise vimconn.VimConnException(
                    "VM is not in active state, stop operation is not allowed",
                    http_code=vimconn.HTTP_Bad_Request,
                )
        elif "forceOff" in action_dict:
            server.stop()  # TODO
        elif "terminate" in action_dict:
            server.delete()
        elif "createImage" in action_dict:
            server.create_image()
            # "path":path_schema,
            # "description":description_schema,
            # "name":name_schema,
            # "metadata":metadata_schema,
            # "imageRef": id_schema,
            # "disk": {"oneOf":[{"type": "null"}, {"type":"string"}] },
        elif "rebuild" in action_dict:
            server.rebuild(server.image["id"])
        elif "reboot" in action_dict:
            server.reboot()  # reboot_type="SOFT"
        elif "console" in action_dict:
            console_type = action_dict["console"]

            if console_type is None or console_type == "novnc":
                console_dict = server.get_vnc_console("novnc")
            elif console_type == "xvpvnc":
                console_dict = server.get_vnc_console(console_type)
            elif console_type == "rdp-html5":
                console_dict = server.get_rdp_console(console_type)
            elif console_type == "spice-html5":
                console_dict = server.get_spice_console(console_type)
            else:
                raise vimconn.VimConnException(
                    "console type '{}' not allowed".format(console_type),
                    http_code=vimconn.HTTP_Bad_Request,
                )

            try:
                console_url = console_dict["console"]["url"]
                # parse console_url
                protocol_index = console_url.find("//")
                suffix_index = (
                    console_url[protocol_index + 2 :].find("/") + protocol_index + 2
                )
                port_index = (
                    console_url[protocol_index + 2 : suffix_index].find(":")
                    + protocol_index
                    + 2
                )

                if protocol_index < 0 or port_index < 0 or suffix_index < 0:
                    raise vimconn.VimConnException(
                        "Unexpected response from VIM " + str(console_dict)
                    )

                console_dict2 = {
                    "protocol": console_url[0:protocol_index],
                    "server": console_url[protocol_index + 2 : port_index],
                    "port": int(console_url[port_index + 1 : suffix_index]),
                    "suffix": console_url[suffix_index + 1 :],
                }

                return console_dict2
            except Exception:
                raise vimconn.VimConnException(
                    "Unexpected response from VIM " + str(console_dict)
                )

        return None

    # ###### VIO Specific Changes #########
    def _generate_vlanID(self):
        """
        Method to get unused vlanID
            Args:
                None
            Returns:
                vlanID
        """
        # Get used VLAN IDs
        usedVlanIDs = []
        networks = self.get_network_list()

        for net in networks:
            if net.get("provider:segmentation_id"):
                usedVlanIDs.append(net.get("provider:segmentation_id"))

        used_vlanIDs = set(usedVlanIDs)

        # find unused VLAN ID
        for vlanID_range in self.config.get("dataplane_net_vlan_range"):
            try:
                start_vlanid, end_vlanid = map(
                    int, vlanID_range.replace(" ", "").split("-")
                )

                for vlanID in range(start_vlanid, end_vlanid + 1):
                    if vlanID not in used_vlanIDs:
                        return vlanID
            except Exception as exp:
                raise vimconn.VimConnException(
                    "Exception {} occurred while generating VLAN ID.".format(exp)
                )
        else:
            raise vimconn.VimConnConflictException(
                "Unable to create the SRIOV VLAN network. All given Vlan IDs {} are in use.".format(
                    self.config.get("dataplane_net_vlan_range")
                )
            )

    def _generate_multisegment_vlanID(self):
        """
        Method to get unused vlanID
        Args:
            None
        Returns:
            vlanID
        """
        # Get used VLAN IDs
        usedVlanIDs = []
        networks = self.get_network_list()
        for net in networks:
            if net.get("provider:network_type") == "vlan" and net.get(
                "provider:segmentation_id"
            ):
                usedVlanIDs.append(net.get("provider:segmentation_id"))
            elif net.get("segments"):
                for segment in net.get("segments"):
                    if segment.get("provider:network_type") == "vlan" and segment.get(
                        "provider:segmentation_id"
                    ):
                        usedVlanIDs.append(segment.get("provider:segmentation_id"))

        used_vlanIDs = set(usedVlanIDs)

        # find unused VLAN ID
        for vlanID_range in self.config.get("multisegment_vlan_range"):
            try:
                start_vlanid, end_vlanid = map(
                    int, vlanID_range.replace(" ", "").split("-")
                )

                for vlanID in range(start_vlanid, end_vlanid + 1):
                    if vlanID not in used_vlanIDs:
                        return vlanID
            except Exception as exp:
                raise vimconn.VimConnException(
                    "Exception {} occurred while generating VLAN ID.".format(exp)
                )
        else:
            raise vimconn.VimConnConflictException(
                "Unable to create the VLAN segment. All VLAN IDs {} are in use.".format(
                    self.config.get("multisegment_vlan_range")
                )
            )

    def _validate_vlan_ranges(self, input_vlan_range, text_vlan_range):
        """
        Method to validate user given vlanID ranges
            Args:  None
            Returns: None
        """
        for vlanID_range in input_vlan_range:
            vlan_range = vlanID_range.replace(" ", "")
            # validate format
            vlanID_pattern = r"(\d)*-(\d)*$"
            match_obj = re.match(vlanID_pattern, vlan_range)
            if not match_obj:
                raise vimconn.VimConnConflictException(
                    "Invalid VLAN range for {}: {}.You must provide "
                    "'{}' in format [start_ID - end_ID].".format(
                        text_vlan_range, vlanID_range, text_vlan_range
                    )
                )

            start_vlanid, end_vlanid = map(int, vlan_range.split("-"))
            if start_vlanid <= 0:
                raise vimconn.VimConnConflictException(
                    "Invalid VLAN range for {}: {}. Start ID can not be zero. For VLAN "
                    "networks valid IDs are 1 to 4094 ".format(
                        text_vlan_range, vlanID_range
                    )
                )

            if end_vlanid > 4094:
                raise vimconn.VimConnConflictException(
                    "Invalid VLAN range for {}: {}. End VLAN ID can not be "
                    "greater than 4094. For VLAN networks valid IDs are 1 to 4094 ".format(
                        text_vlan_range, vlanID_range
                    )
                )

            if start_vlanid > end_vlanid:
                raise vimconn.VimConnConflictException(
                    "Invalid VLAN range for {}: {}. You must provide '{}'"
                    " in format start_ID - end_ID and start_ID < end_ID ".format(
                        text_vlan_range, vlanID_range, text_vlan_range
                    )
                )

    def get_hosts_info(self):
        """Get the information of deployed hosts
        Returns the hosts content"""
        self.logger.debug("osconnector: Getting Host info from VIM")

        try:
            h_list = []
            self._reload_connection()
            hypervisors = self.nova.hypervisors.list()

            for hype in hypervisors:
                h_list.append(hype.to_dict())

            return 1, {"hosts": h_list}
        except nvExceptions.NotFound as e:
            error_value = -vimconn.HTTP_Not_Found
            error_text = str(e) if len(e.args) == 0 else str(e.args[0])
        except (ksExceptions.ClientException, nvExceptions.ClientException) as e:
            error_value = -vimconn.HTTP_Bad_Request
            error_text = (
                type(e).__name__
                + ": "
                + (str(e) if len(e.args) == 0 else str(e.args[0]))
            )

        # TODO insert exception vimconn.HTTP_Unauthorized
        # if reaching here is because an exception
        self.logger.debug("get_hosts_info " + error_text)

        return error_value, error_text

    def get_hosts(self, vim_tenant):
        """Get the hosts and deployed instances
        Returns the hosts content"""
        r, hype_dict = self.get_hosts_info()

        if r < 0:
            return r, hype_dict

        hypervisors = hype_dict["hosts"]

        try:
            servers = self.nova.servers.list()
            for hype in hypervisors:
                for server in servers:
                    if (
                        server.to_dict()["OS-EXT-SRV-ATTR:hypervisor_hostname"]
                        == hype["hypervisor_hostname"]
                    ):
                        if "vm" in hype:
                            hype["vm"].append(server.id)
                        else:
                            hype["vm"] = [server.id]

            return 1, hype_dict
        except nvExceptions.NotFound as e:
            error_value = -vimconn.HTTP_Not_Found
            error_text = str(e) if len(e.args) == 0 else str(e.args[0])
        except (ksExceptions.ClientException, nvExceptions.ClientException) as e:
            error_value = -vimconn.HTTP_Bad_Request
            error_text = (
                type(e).__name__
                + ": "
                + (str(e) if len(e.args) == 0 else str(e.args[0]))
            )

        # TODO insert exception vimconn.HTTP_Unauthorized
        # if reaching here is because an exception
        self.logger.debug("get_hosts " + error_text)

        return error_value, error_text

    def new_classification(self, name, ctype, definition):
        self.logger.debug(
            "Adding a new (Traffic) Classification to VIM, named %s", name
        )

        try:
            new_class = None
            self._reload_connection()

            if ctype not in supportedClassificationTypes:
                raise vimconn.VimConnNotSupportedException(
                    "OpenStack VIM connector does not support provided "
                    "Classification Type {}, supported ones are: {}".format(
                        ctype, supportedClassificationTypes
                    )
                )

            if not self._validate_classification(ctype, definition):
                raise vimconn.VimConnException(
                    "Incorrect Classification definition for the type specified."
                )

            classification_dict = definition
            classification_dict["name"] = name

            self.logger.info(
                "Adding a new (Traffic) Classification to VIM, named {} and {}.".format(
                    name, classification_dict
                )
            )
            new_class = self.neutron.create_sfc_flow_classifier(
                {"flow_classifier": classification_dict}
            )

            return new_class["flow_classifier"]["id"]
        except (
            neExceptions.ConnectionFailed,
            ksExceptions.ClientException,
            neExceptions.NeutronException,
            ConnectionError,
        ) as e:
            self.logger.error("Creation of Classification failed.")
            self._format_exception(e)

    def get_classification(self, class_id):
        self.logger.debug(" Getting Classification %s from VIM", class_id)
        filter_dict = {"id": class_id}
        class_list = self.get_classification_list(filter_dict)

        if len(class_list) == 0:
            raise vimconn.VimConnNotFoundException(
                "Classification '{}' not found".format(class_id)
            )
        elif len(class_list) > 1:
            raise vimconn.VimConnConflictException(
                "Found more than one Classification with this criteria"
            )

        classification = class_list[0]

        return classification

    def get_classification_list(self, filter_dict={}):
        self.logger.debug(
            "Getting Classifications from VIM filter: '%s'", str(filter_dict)
        )

        try:
            filter_dict_os = filter_dict.copy()
            self._reload_connection()

            if self.api_version3 and "tenant_id" in filter_dict_os:
                filter_dict_os["project_id"] = filter_dict_os.pop("tenant_id")

            classification_dict = self.neutron.list_sfc_flow_classifiers(
                **filter_dict_os
            )
            classification_list = classification_dict["flow_classifiers"]
            self.__classification_os2mano(classification_list)

            return classification_list
        except (
            neExceptions.ConnectionFailed,
            ksExceptions.ClientException,
            neExceptions.NeutronException,
            ConnectionError,
        ) as e:
            self._format_exception(e)

    def delete_classification(self, class_id):
        self.logger.debug("Deleting Classification '%s' from VIM", class_id)

        try:
            self._reload_connection()
            self.neutron.delete_sfc_flow_classifier(class_id)

            return class_id
        except (
            neExceptions.ConnectionFailed,
            neExceptions.NeutronException,
            ksExceptions.ClientException,
            neExceptions.NeutronException,
            ConnectionError,
        ) as e:
            self._format_exception(e)

    def new_sfi(self, name, ingress_ports, egress_ports, sfc_encap=True):
        self.logger.debug(
            "Adding a new Service Function Instance to VIM, named '%s'", name
        )

        try:
            new_sfi = None
            self._reload_connection()
            correlation = None

            if sfc_encap:
                correlation = "nsh"

            if len(ingress_ports) != 1:
                raise vimconn.VimConnNotSupportedException(
                    "OpenStack VIM connector can only have 1 ingress port per SFI"
                )

            if len(egress_ports) != 1:
                raise vimconn.VimConnNotSupportedException(
                    "OpenStack VIM connector can only have 1 egress port per SFI"
                )

            sfi_dict = {
                "name": name,
                "ingress": ingress_ports[0],
                "egress": egress_ports[0],
                "service_function_parameters": {"correlation": correlation},
            }
            self.logger.info("Adding a new SFI to VIM, {}.".format(sfi_dict))
            new_sfi = self.neutron.create_sfc_port_pair({"port_pair": sfi_dict})

            return new_sfi["port_pair"]["id"]
        except (
            neExceptions.ConnectionFailed,
            ksExceptions.ClientException,
            neExceptions.NeutronException,
            ConnectionError,
        ) as e:
            if new_sfi:
                try:
                    self.neutron.delete_sfc_port_pair(new_sfi["port_pair"]["id"])
                except Exception:
                    self.logger.error(
                        "Creation of Service Function Instance failed, with "
                        "subsequent deletion failure as well."
                    )

            self._format_exception(e)

    def get_sfi(self, sfi_id):
        self.logger.debug("Getting Service Function Instance %s from VIM", sfi_id)
        filter_dict = {"id": sfi_id}
        sfi_list = self.get_sfi_list(filter_dict)

        if len(sfi_list) == 0:
            raise vimconn.VimConnNotFoundException(
                "Service Function Instance '{}' not found".format(sfi_id)
            )
        elif len(sfi_list) > 1:
            raise vimconn.VimConnConflictException(
                "Found more than one Service Function Instance with this criteria"
            )

        sfi = sfi_list[0]

        return sfi

    def get_sfi_list(self, filter_dict={}):
        self.logger.debug(
            "Getting Service Function Instances from VIM filter: '%s'", str(filter_dict)
        )

        try:
            self._reload_connection()
            filter_dict_os = filter_dict.copy()

            if self.api_version3 and "tenant_id" in filter_dict_os:
                filter_dict_os["project_id"] = filter_dict_os.pop("tenant_id")

            sfi_dict = self.neutron.list_sfc_port_pairs(**filter_dict_os)
            sfi_list = sfi_dict["port_pairs"]
            self.__sfi_os2mano(sfi_list)

            return sfi_list
        except (
            neExceptions.ConnectionFailed,
            ksExceptions.ClientException,
            neExceptions.NeutronException,
            ConnectionError,
        ) as e:
            self._format_exception(e)

    def delete_sfi(self, sfi_id):
        self.logger.debug("Deleting Service Function Instance '%s' from VIM", sfi_id)

        try:
            self._reload_connection()
            self.neutron.delete_sfc_port_pair(sfi_id)

            return sfi_id
        except (
            neExceptions.ConnectionFailed,
            neExceptions.NeutronException,
            ksExceptions.ClientException,
            neExceptions.NeutronException,
            ConnectionError,
        ) as e:
            self._format_exception(e)

    def new_sf(self, name, sfis, sfc_encap=True):
        self.logger.debug("Adding a new Service Function to VIM, named '%s'", name)

        new_sf = None

        try:
            self._reload_connection()

            for instance in sfis:
                sfi = self.get_sfi(instance)

                if sfi.get("sfc_encap") != sfc_encap:
                    raise vimconn.VimConnNotSupportedException(
                        "OpenStack VIM connector requires all SFIs of the "
                        "same SF to share the same SFC Encapsulation"
                    )

            sf_dict = {"name": name, "port_pairs": sfis}

            self.logger.info("Adding a new SF to VIM, {}.".format(sf_dict))
            new_sf = self.neutron.create_sfc_port_pair_group(
                {"port_pair_group": sf_dict}
            )

            return new_sf["port_pair_group"]["id"]
        except (
            neExceptions.ConnectionFailed,
            ksExceptions.ClientException,
            neExceptions.NeutronException,
            ConnectionError,
        ) as e:
            if new_sf:
                try:
                    new_sf_id = new_sf.get("port_pair_group").get("id")
                    self.neutron.delete_sfc_port_pair_group(new_sf_id)
                except Exception:
                    self.logger.error(
                        "Creation of Service Function failed, with "
                        "subsequent deletion failure as well."
                    )

            self._format_exception(e)

    def get_sf(self, sf_id):
        self.logger.debug("Getting Service Function %s from VIM", sf_id)
        filter_dict = {"id": sf_id}
        sf_list = self.get_sf_list(filter_dict)

        if len(sf_list) == 0:
            raise vimconn.VimConnNotFoundException(
                "Service Function '{}' not found".format(sf_id)
            )
        elif len(sf_list) > 1:
            raise vimconn.VimConnConflictException(
                "Found more than one Service Function with this criteria"
            )

        sf = sf_list[0]

        return sf

    def get_sf_list(self, filter_dict={}):
        self.logger.debug(
            "Getting Service Function from VIM filter: '%s'", str(filter_dict)
        )

        try:
            self._reload_connection()
            filter_dict_os = filter_dict.copy()

            if self.api_version3 and "tenant_id" in filter_dict_os:
                filter_dict_os["project_id"] = filter_dict_os.pop("tenant_id")

            sf_dict = self.neutron.list_sfc_port_pair_groups(**filter_dict_os)
            sf_list = sf_dict["port_pair_groups"]
            self.__sf_os2mano(sf_list)

            return sf_list
        except (
            neExceptions.ConnectionFailed,
            ksExceptions.ClientException,
            neExceptions.NeutronException,
            ConnectionError,
        ) as e:
            self._format_exception(e)

    def delete_sf(self, sf_id):
        self.logger.debug("Deleting Service Function '%s' from VIM", sf_id)

        try:
            self._reload_connection()
            self.neutron.delete_sfc_port_pair_group(sf_id)

            return sf_id
        except (
            neExceptions.ConnectionFailed,
            neExceptions.NeutronException,
            ksExceptions.ClientException,
            neExceptions.NeutronException,
            ConnectionError,
        ) as e:
            self._format_exception(e)

    def new_sfp(self, name, classifications, sfs, sfc_encap=True, spi=None):
        self.logger.debug("Adding a new Service Function Path to VIM, named '%s'", name)

        new_sfp = None

        try:
            self._reload_connection()
            # In networking-sfc the MPLS encapsulation is legacy
            # should be used when no full SFC Encapsulation is intended
            correlation = "mpls"

            if sfc_encap:
                correlation = "nsh"

            sfp_dict = {
                "name": name,
                "flow_classifiers": classifications,
                "port_pair_groups": sfs,
                "chain_parameters": {"correlation": correlation},
            }

            if spi:
                sfp_dict["chain_id"] = spi

            self.logger.info("Adding a new SFP to VIM, {}.".format(sfp_dict))
            new_sfp = self.neutron.create_sfc_port_chain({"port_chain": sfp_dict})

            return new_sfp["port_chain"]["id"]
        except (
            neExceptions.ConnectionFailed,
            ksExceptions.ClientException,
            neExceptions.NeutronException,
            ConnectionError,
        ) as e:
            if new_sfp:
                try:
                    new_sfp_id = new_sfp.get("port_chain").get("id")
                    self.neutron.delete_sfc_port_chain(new_sfp_id)
                except Exception:
                    self.logger.error(
                        "Creation of Service Function Path failed, with "
                        "subsequent deletion failure as well."
                    )

            self._format_exception(e)

    def get_sfp(self, sfp_id):
        self.logger.debug(" Getting Service Function Path %s from VIM", sfp_id)

        filter_dict = {"id": sfp_id}
        sfp_list = self.get_sfp_list(filter_dict)

        if len(sfp_list) == 0:
            raise vimconn.VimConnNotFoundException(
                "Service Function Path '{}' not found".format(sfp_id)
            )
        elif len(sfp_list) > 1:
            raise vimconn.VimConnConflictException(
                "Found more than one Service Function Path with this criteria"
            )

        sfp = sfp_list[0]

        return sfp

    def get_sfp_list(self, filter_dict={}):
        self.logger.debug(
            "Getting Service Function Paths from VIM filter: '%s'", str(filter_dict)
        )

        try:
            self._reload_connection()
            filter_dict_os = filter_dict.copy()

            if self.api_version3 and "tenant_id" in filter_dict_os:
                filter_dict_os["project_id"] = filter_dict_os.pop("tenant_id")

            sfp_dict = self.neutron.list_sfc_port_chains(**filter_dict_os)
            sfp_list = sfp_dict["port_chains"]
            self.__sfp_os2mano(sfp_list)

            return sfp_list
        except (
            neExceptions.ConnectionFailed,
            ksExceptions.ClientException,
            neExceptions.NeutronException,
            ConnectionError,
        ) as e:
            self._format_exception(e)

    def delete_sfp(self, sfp_id):
        self.logger.debug("Deleting Service Function Path '%s' from VIM", sfp_id)

        try:
            self._reload_connection()
            self.neutron.delete_sfc_port_chain(sfp_id)

            return sfp_id
        except (
            neExceptions.ConnectionFailed,
            neExceptions.NeutronException,
            ksExceptions.ClientException,
            neExceptions.NeutronException,
            ConnectionError,
        ) as e:
            self._format_exception(e)

    def refresh_sfps_status(self, sfp_list):
        """Get the status of the service function path
        Params: the list of sfp identifiers
        Returns a dictionary with:
            vm_id:          #VIM id of this service function path
                status:     #Mandatory. Text with one of:
                            #  DELETED (not found at vim)
                            #  VIM_ERROR (Cannot connect to VIM, VIM response error, ...)
                            #  OTHER (Vim reported other status not understood)
                            #  ERROR (VIM indicates an ERROR status)
                            #  ACTIVE,
                            #  CREATING (on building process)
                error_msg:  #Text with VIM error message, if any. Or the VIM connection ERROR
                vim_info:   #Text with plain information obtained from vim (yaml.safe_dump)F
        """
        sfp_dict = {}
        self.logger.debug(
            "refresh_sfps status: Getting tenant SFP information from VIM"
        )

        for sfp_id in sfp_list:
            sfp = {}

            try:
                sfp_vim = self.get_sfp(sfp_id)

                if sfp_vim["spi"]:
                    sfp["status"] = vmStatus2manoFormat["ACTIVE"]
                else:
                    sfp["status"] = "OTHER"
                    sfp["error_msg"] = "VIM status reported " + sfp["status"]

                sfp["vim_info"] = self.serialize(sfp_vim)

                if sfp_vim.get("fault"):
                    sfp["error_msg"] = str(sfp_vim["fault"])
            except vimconn.VimConnNotFoundException as e:
                self.logger.error("Exception getting sfp status: %s", str(e))
                sfp["status"] = "DELETED"
                sfp["error_msg"] = str(e)
            except vimconn.VimConnException as e:
                self.logger.error("Exception getting sfp status: %s", str(e))
                sfp["status"] = "VIM_ERROR"
                sfp["error_msg"] = str(e)

            sfp_dict[sfp_id] = sfp

        return sfp_dict

    def refresh_sfis_status(self, sfi_list):
        """Get the status of the service function instances
        Params: the list of sfi identifiers
        Returns a dictionary with:
            vm_id:          #VIM id of this service function instance
                status:     #Mandatory. Text with one of:
                            #  DELETED (not found at vim)
                            #  VIM_ERROR (Cannot connect to VIM, VIM response error, ...)
                            #  OTHER (Vim reported other status not understood)
                            #  ERROR (VIM indicates an ERROR status)
                            #  ACTIVE,
                            #  CREATING (on building process)
                error_msg:  #Text with VIM error message, if any. Or the VIM connection ERROR
                vim_info:   #Text with plain information obtained from vim (yaml.safe_dump)
        """
        sfi_dict = {}
        self.logger.debug(
            "refresh_sfis status: Getting tenant sfi information from VIM"
        )

        for sfi_id in sfi_list:
            sfi = {}

            try:
                sfi_vim = self.get_sfi(sfi_id)

                if sfi_vim:
                    sfi["status"] = vmStatus2manoFormat["ACTIVE"]
                else:
                    sfi["status"] = "OTHER"
                    sfi["error_msg"] = "VIM status reported " + sfi["status"]

                sfi["vim_info"] = self.serialize(sfi_vim)

                if sfi_vim.get("fault"):
                    sfi["error_msg"] = str(sfi_vim["fault"])
            except vimconn.VimConnNotFoundException as e:
                self.logger.error("Exception getting sfi status: %s", str(e))
                sfi["status"] = "DELETED"
                sfi["error_msg"] = str(e)
            except vimconn.VimConnException as e:
                self.logger.error("Exception getting sfi status: %s", str(e))
                sfi["status"] = "VIM_ERROR"
                sfi["error_msg"] = str(e)

            sfi_dict[sfi_id] = sfi

        return sfi_dict

    def refresh_sfs_status(self, sf_list):
        """Get the status of the service functions
        Params: the list of sf identifiers
        Returns a dictionary with:
            vm_id:          #VIM id of this service function
                status:     #Mandatory. Text with one of:
                            #  DELETED (not found at vim)
                            #  VIM_ERROR (Cannot connect to VIM, VIM response error, ...)
                            #  OTHER (Vim reported other status not understood)
                            #  ERROR (VIM indicates an ERROR status)
                            #  ACTIVE,
                            #  CREATING (on building process)
                error_msg:  #Text with VIM error message, if any. Or the VIM connection ERROR
                vim_info:   #Text with plain information obtained from vim (yaml.safe_dump)
        """
        sf_dict = {}
        self.logger.debug("refresh_sfs status: Getting tenant sf information from VIM")

        for sf_id in sf_list:
            sf = {}

            try:
                sf_vim = self.get_sf(sf_id)

                if sf_vim:
                    sf["status"] = vmStatus2manoFormat["ACTIVE"]
                else:
                    sf["status"] = "OTHER"
                    sf["error_msg"] = "VIM status reported " + sf_vim["status"]

                sf["vim_info"] = self.serialize(sf_vim)

                if sf_vim.get("fault"):
                    sf["error_msg"] = str(sf_vim["fault"])
            except vimconn.VimConnNotFoundException as e:
                self.logger.error("Exception getting sf status: %s", str(e))
                sf["status"] = "DELETED"
                sf["error_msg"] = str(e)
            except vimconn.VimConnException as e:
                self.logger.error("Exception getting sf status: %s", str(e))
                sf["status"] = "VIM_ERROR"
                sf["error_msg"] = str(e)

            sf_dict[sf_id] = sf

        return sf_dict

    def refresh_classifications_status(self, classification_list):
        """Get the status of the classifications
        Params: the list of classification identifiers
        Returns a dictionary with:
            vm_id:          #VIM id of this classifier
                status:     #Mandatory. Text with one of:
                            #  DELETED (not found at vim)
                            #  VIM_ERROR (Cannot connect to VIM, VIM response error, ...)
                            #  OTHER (Vim reported other status not understood)
                            #  ERROR (VIM indicates an ERROR status)
                            #  ACTIVE,
                            #  CREATING (on building process)
                error_msg:  #Text with VIM error message, if any. Or the VIM connection ERROR
                vim_info:   #Text with plain information obtained from vim (yaml.safe_dump)
        """
        classification_dict = {}
        self.logger.debug(
            "refresh_classifications status: Getting tenant classification information from VIM"
        )

        for classification_id in classification_list:
            classification = {}

            try:
                classification_vim = self.get_classification(classification_id)

                if classification_vim:
                    classification["status"] = vmStatus2manoFormat["ACTIVE"]
                else:
                    classification["status"] = "OTHER"
                    classification["error_msg"] = (
                        "VIM status reported " + classification["status"]
                    )

                classification["vim_info"] = self.serialize(classification_vim)

                if classification_vim.get("fault"):
                    classification["error_msg"] = str(classification_vim["fault"])
            except vimconn.VimConnNotFoundException as e:
                self.logger.error("Exception getting classification status: %s", str(e))
                classification["status"] = "DELETED"
                classification["error_msg"] = str(e)
            except vimconn.VimConnException as e:
                self.logger.error("Exception getting classification status: %s", str(e))
                classification["status"] = "VIM_ERROR"
                classification["error_msg"] = str(e)

            classification_dict[classification_id] = classification

        return classification_dict

    @catch_any_exception
    def new_affinity_group(self, affinity_group_data):
        """Adds a server group to VIM
            affinity_group_data contains a dictionary with information, keys:
                name: name in VIM for the server group
                type: affinity or anti-affinity
                scope: Only nfvi-node allowed
        Returns the server group identifier"""
        self.logger.debug("Adding Server Group '%s'", str(affinity_group_data))
        name = affinity_group_data["name"]
        policy = affinity_group_data["type"]
        self._reload_connection()
        new_server_group = self.nova.server_groups.create(name, policy)
        return new_server_group.id

    @catch_any_exception
    def get_affinity_group(self, affinity_group_id):
        """Obtain server group details from the VIM. Returns the server group detais as a dict"""
        self.logger.debug("Getting flavor '%s'", affinity_group_id)
        self._reload_connection()
        server_group = self.nova.server_groups.find(id=affinity_group_id)
        return server_group.to_dict()

    @catch_any_exception
    def delete_affinity_group(self, affinity_group_id):
        """Deletes a server group from the VIM. Returns the old affinity_group_id"""
        self.logger.debug("Getting server group '%s'", affinity_group_id)
        self._reload_connection()
        self.nova.server_groups.delete(affinity_group_id)
        return affinity_group_id

    @catch_any_exception
    def get_vdu_state(self, vm_id, host_is_required=False) -> list:
        """Getting the state of a VDU.
        Args:
            vm_id   (str): ID of an instance
            host_is_required    (Boolean): If the VIM account is non-admin, host info does not appear in server_dict
                                           and if this is set to True, it raises KeyError.
        Returns:
            vdu_data    (list): VDU details including state, flavor, host_info, AZ
        """
        self.logger.debug("Getting the status of VM")
        self.logger.debug("VIM VM ID %s", vm_id)
        self._reload_connection()
        server_dict = self._find_nova_server(vm_id)
        srv_attr = "OS-EXT-SRV-ATTR:host"
        host_info = (
            server_dict[srv_attr] if host_is_required else server_dict.get(srv_attr)
        )
        vdu_data = [
            server_dict["status"],
            server_dict["flavor"]["id"],
            host_info,
            server_dict["OS-EXT-AZ:availability_zone"],
        ]
        self.logger.debug("vdu_data %s", vdu_data)
        return vdu_data

    def check_compute_availability(self, host, server_flavor_details):
        self._reload_connection()
        hypervisor_search = self.nova.hypervisors.search(
            hypervisor_match=host, servers=True
        )
        for hypervisor in hypervisor_search:
            hypervisor_id = hypervisor.to_dict()["id"]
            hypervisor_details = self.nova.hypervisors.get(hypervisor=hypervisor_id)
            hypervisor_dict = hypervisor_details.to_dict()
            hypervisor_temp = json.dumps(hypervisor_dict)
            hypervisor_json = json.loads(hypervisor_temp)
            resources_available = [
                hypervisor_json["free_ram_mb"],
                hypervisor_json["disk_available_least"],
                hypervisor_json["vcpus"] - hypervisor_json["vcpus_used"],
            ]
            compute_available = all(
                x > y for x, y in zip(resources_available, server_flavor_details)
            )
            if compute_available:
                return host

    def check_availability_zone(
        self, old_az, server_flavor_details, old_host, host=None
    ):
        self._reload_connection()
        az_check = {"zone_check": False, "compute_availability": None}
        aggregates_list = self.nova.aggregates.list()
        for aggregate in aggregates_list:
            aggregate_details = aggregate.to_dict()
            aggregate_temp = json.dumps(aggregate_details)
            aggregate_json = json.loads(aggregate_temp)
            if aggregate_json["availability_zone"] == old_az:
                hosts_list = aggregate_json["hosts"]
                if host is not None:
                    if host in hosts_list:
                        az_check["zone_check"] = True
                        available_compute_id = self.check_compute_availability(
                            host, server_flavor_details
                        )
                        if available_compute_id is not None:
                            az_check["compute_availability"] = available_compute_id
                else:
                    for check_host in hosts_list:
                        if check_host != old_host:
                            available_compute_id = self.check_compute_availability(
                                check_host, server_flavor_details
                            )
                            if available_compute_id is not None:
                                az_check["zone_check"] = True
                                az_check["compute_availability"] = available_compute_id
                                break
                    else:
                        az_check["zone_check"] = True
        return az_check

    @catch_any_exception
    def migrate_instance(self, vm_id, compute_host=None):
        """
        Migrate a vdu
        param:
            vm_id: ID of an instance
            compute_host: Host to migrate the vdu to
        """
        self._reload_connection()
        vm_state = False
        instance_state = self.get_vdu_state(vm_id, host_is_required=True)
        server_flavor_id = instance_state[1]
        server_hypervisor_name = instance_state[2]
        server_availability_zone = instance_state[3]
        server_flavor = self.nova.flavors.find(id=server_flavor_id).to_dict()
        server_flavor_details = [
            server_flavor["ram"],
            server_flavor["disk"],
            server_flavor["vcpus"],
        ]
        if compute_host == server_hypervisor_name:
            raise vimconn.VimConnException(
                "Unable to migrate instance '{}' to the same host '{}'".format(
                    vm_id, compute_host
                ),
                http_code=vimconn.HTTP_Bad_Request,
            )
        az_status = self.check_availability_zone(
            server_availability_zone,
            server_flavor_details,
            server_hypervisor_name,
            compute_host,
        )
        availability_zone_check = az_status["zone_check"]
        available_compute_id = az_status.get("compute_availability")

        if availability_zone_check is False:
            raise vimconn.VimConnException(
                "Unable to migrate instance '{}' to a different availability zone".format(
                    vm_id
                ),
                http_code=vimconn.HTTP_Bad_Request,
            )
        if available_compute_id is not None:
            # disk_over_commit parameter for live_migrate method is not valid for Nova API version >= 2.25
            self.nova.servers.live_migrate(
                server=vm_id,
                host=available_compute_id,
                block_migration=True,
            )
            state = "MIGRATING"
            changed_compute_host = ""
            if state == "MIGRATING":
                vm_state = self.__wait_for_vm(vm_id, "ACTIVE")
                changed_compute_host = self.get_vdu_state(vm_id, host_is_required=True)[
                    2
                ]
            if vm_state and changed_compute_host == available_compute_id:
                self.logger.debug(
                    "Instance '{}' migrated to the new compute host '{}'".format(
                        vm_id, changed_compute_host
                    )
                )
                return state, available_compute_id
            else:
                raise vimconn.VimConnException(
                    "Migration Failed. Instance '{}' not moved to the new host {}".format(
                        vm_id, available_compute_id
                    ),
                    http_code=vimconn.HTTP_Bad_Request,
                )
        else:
            raise vimconn.VimConnException(
                "Compute '{}' not available or does not have enough resources to migrate the instance".format(
                    available_compute_id
                ),
                http_code=vimconn.HTTP_Bad_Request,
            )

    @catch_any_exception
    def resize_instance(self, vm_id, new_flavor_id):
        """
        For resizing the vm based on the given
        flavor details
        param:
            vm_id : ID of an instance
            new_flavor_id : Flavor id to be resized
        Return the status of a resized instance
        """
        self._reload_connection()
        self.logger.debug("resize the flavor of an instance")
        instance_status, old_flavor_id, compute_host, az = self.get_vdu_state(vm_id)
        old_flavor_disk = self.nova.flavors.find(id=old_flavor_id).to_dict()["disk"]
        new_flavor_disk = self.nova.flavors.find(id=new_flavor_id).to_dict()["disk"]
        if instance_status == "ACTIVE" or instance_status == "SHUTOFF":
            if old_flavor_disk > new_flavor_disk:
                raise nvExceptions.BadRequest(
                    400,
                    message="Server disk resize failed. Resize to lower disk flavor is not allowed",
                )
            else:
                self.nova.servers.resize(server=vm_id, flavor=new_flavor_id)
                vm_state = self.__wait_for_vm(vm_id, "VERIFY_RESIZE")
                if vm_state:
                    instance_resized_status = self.confirm_resize(
                        vm_id, instance_status
                    )
                    return instance_resized_status
                else:
                    raise nvExceptions.BadRequest(
                        409,
                        message="Cannot 'resize' vm_state is in ERROR",
                    )

        else:
            self.logger.debug("ERROR : Instance is not in ACTIVE or SHUTOFF state")
            raise nvExceptions.BadRequest(
                409,
                message="Cannot 'resize' instance while it is in vm_state resized",
            )

    def confirm_resize(self, vm_id, instance_state):
        """
        Confirm the resize of an instance
        param:
            vm_id: ID of an instance
        """
        self._reload_connection()
        self.nova.servers.confirm_resize(server=vm_id)
        if self.get_vdu_state(vm_id)[0] == "VERIFY_RESIZE":
            self.__wait_for_vm(vm_id, instance_state)
        instance_status = self.get_vdu_state(vm_id)[0]
        return instance_status

    def get_monitoring_data(self):
        try:
            self.logger.debug("Getting servers and ports data from Openstack VIMs.")
            self._reload_connection()
            all_servers = self.nova.servers.list(detailed=True)
            try:
                for server in all_servers:
                    if server.flavor.get("original_name"):
                        server.flavor["id"] = self.nova.flavors.find(
                            name=server.flavor["original_name"]
                        ).id
            except nClient.exceptions.NotFound as e:
                self.logger.warning(str(e.message))
            all_ports = self.neutron.list_ports()
            return all_servers, all_ports
        except Exception as e:
            raise vimconn.VimConnException(
                f"Exception in monitoring while getting VMs and ports status: {str(e)}"
            )
