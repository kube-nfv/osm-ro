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
#
# For those usages not covered by the Apache License, Version 2.0 please
# contact with: nfvlabs@tid.es
##

"""
vimconn implement an Abstract class for the vim connector plugins
 with the definition of the method to be implemented.
"""

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from http import HTTPStatus
from io import StringIO
import logging
import socket
import sys
import traceback
import warnings

import paramiko
import yaml

__author__ = "Alfonso Tierno, Igor D.C."
__date__ = "$14-aug-2017 23:59:59$"


def deprecated(message):
    def deprecated_decorator(func):
        def deprecated_func(*args, **kwargs):
            warnings.warn(
                "{} is a deprecated function. {}".format(func.__name__, message),
                category=DeprecationWarning,
                stacklevel=2,
            )
            warnings.simplefilter("default", DeprecationWarning)

            return func(*args, **kwargs)

        return deprecated_func

    return deprecated_decorator


# Error variables
HTTP_Bad_Request = HTTPStatus.BAD_REQUEST.value
HTTP_Unauthorized = HTTPStatus.UNAUTHORIZED.value
HTTP_Not_Found = HTTPStatus.NOT_FOUND.value
HTTP_Method_Not_Allowed = HTTPStatus.METHOD_NOT_ALLOWED.value
HTTP_Request_Timeout = HTTPStatus.REQUEST_TIMEOUT.value
HTTP_Conflict = HTTPStatus.CONFLICT.value
HTTP_Not_Implemented = HTTPStatus.NOT_IMPLEMENTED.value
HTTP_Service_Unavailable = HTTPStatus.SERVICE_UNAVAILABLE.value
HTTP_Internal_Server_Error = HTTPStatus.INTERNAL_SERVER_ERROR.value


class VimConnException(Exception):
    """Common and base class Exception for all VimConnector exceptions"""

    def __init__(self, message, http_code=HTTP_Bad_Request):
        Exception.__init__(self, message)
        self.http_code = http_code


class VimConnConnectionException(VimConnException):
    """Connectivity error with the VIM"""

    def __init__(self, message, http_code=HTTP_Service_Unavailable):
        VimConnException.__init__(self, message, http_code)


class VimConnUnexpectedResponse(VimConnException):
    """Get an wrong response from VIM"""

    def __init__(self, message, http_code=HTTP_Service_Unavailable):
        VimConnException.__init__(self, message, http_code)


class VimConnAuthException(VimConnException):
    """Invalid credentials or authorization to perform this action over the VIM"""

    def __init__(self, message, http_code=HTTP_Unauthorized):
        VimConnException.__init__(self, message, http_code)


class VimConnNotFoundException(VimConnException):
    """The item is not found at VIM"""

    def __init__(self, message, http_code=HTTP_Not_Found):
        VimConnException.__init__(self, message, http_code)


class VimConnConflictException(VimConnException):
    """There is a conflict, e.g. more item found than one"""

    def __init__(self, message, http_code=HTTP_Conflict):
        VimConnException.__init__(self, message, http_code)


class VimConnNotSupportedException(VimConnException):
    """The request is not supported by connector"""

    def __init__(self, message, http_code=HTTP_Service_Unavailable):
        VimConnException.__init__(self, message, http_code)


class VimConnNotImplemented(VimConnException):
    """The method is not implemented by the connector"""

    def __init__(self, message, http_code=HTTP_Not_Implemented):
        VimConnException.__init__(self, message, http_code)


class VimConnInsufficientCredentials(VimConnException):
    """The VIM account does not have efficient permissions to perform the requested operation."""

    def __init__(self, message, http_code=HTTP_Unauthorized):
        VimConnException.__init__(self, message, http_code)


class VimConnector:
    """Abstract base class for all the VIM connector plugins
    These plugins must implement a VimConnector class derived from this
    and all these privated methods
    """

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
        """
        Constructor of VIM. Raise an exception is some needed parameter is missing, but it must not do any connectivity
            checking against the VIM
        :param uuid: internal id of this VIM
        :param name: name assigned to this VIM, can be used for logging
        :param tenant_id: 'tenant_id': (only one of them is mandatory) VIM tenant to be used
        :param tenant_name: 'tenant_name': (only one of them is mandatory) VIM tenant to be used
        :param url: url used for normal operations
        :param url_admin: (optional), url used for administrative tasks
        :param user: user to access
        :param passwd: password
        :param log_level: provided if it should use a different log_level than the general one
        :param config: dictionary with extra VIM information. This contains a consolidate version of VIM config
                    at VIM_ACCOUNT (attach)
        :param persitent_info: dict where the class can store information that will be available among class
                    destroy/creation cycles. This info is unique per VIM/credential. At first call it will contain an
                    empty dict. Useful to store login/tokens information for speed up communication

        """
        self.id = uuid
        self.name = name
        self.url = url
        self.url_admin = url_admin
        self.tenant_id = tenant_id
        self.tenant_name = tenant_name
        self.user = user
        self.passwd = passwd
        self.config = config or {}
        self.availability_zone = None
        self.logger = logging.getLogger("ro.vim")

        if log_level:
            self.logger.setLevel(getattr(logging, log_level))

        if not self.url_admin:  # try to use normal url
            self.url_admin = self.url

    def __getitem__(self, index):
        if index == "tenant_id":
            return self.tenant_id

        if index == "tenant_name":
            return self.tenant_name
        elif index == "id":
            return self.id
        elif index == "name":
            return self.name
        elif index == "user":
            return self.user
        elif index == "passwd":
            return self.passwd
        elif index == "url":
            return self.url
        elif index == "url_admin":
            return self.url_admin
        elif index == "config":
            return self.config
        else:
            raise KeyError("Invalid key '{}'".format(index))

    def __setitem__(self, index, value):
        if index == "tenant_id":
            self.tenant_id = value

        if index == "tenant_name":
            self.tenant_name = value
        elif index == "id":
            self.id = value
        elif index == "name":
            self.name = value
        elif index == "user":
            self.user = value
        elif index == "passwd":
            self.passwd = value
        elif index == "url":
            self.url = value
        elif index == "url_admin":
            self.url_admin = value
        else:
            raise KeyError("Invalid key '{}'".format(index))

    @staticmethod
    def _create_mimemultipart(content_list):
        """Creates a MIMEmultipart text combining the content_list
        :param content_list: list of text scripts to be combined
        :return: str of the created MIMEmultipart. If the list is empty returns None, if the list contains only one
        element MIMEmultipart is not created and this content is returned
        """
        if not content_list:
            return None
        elif len(content_list) == 1:
            return content_list[0]

        combined_message = MIMEMultipart()

        for content in content_list:
            if content.startswith("#include"):
                mime_format = "text/x-include-url"
            elif content.startswith("#include-once"):
                mime_format = "text/x-include-once-url"
            elif content.startswith("#!"):
                mime_format = "text/x-shellscript"
            elif content.startswith("#cloud-config"):
                mime_format = "text/cloud-config"
            elif content.startswith("#cloud-config-archive"):
                mime_format = "text/cloud-config-archive"
            elif content.startswith("#upstart-job"):
                mime_format = "text/upstart-job"
            elif content.startswith("#part-handler"):
                mime_format = "text/part-handler"
            elif content.startswith("#cloud-boothook"):
                mime_format = "text/cloud-boothook"
            else:  # by default
                mime_format = "text/x-shellscript"

            sub_message = MIMEText(content, mime_format, sys.getdefaultencoding())
            combined_message.attach(sub_message)

        return combined_message.as_string()

    def _create_user_data(self, cloud_config):
        """
        Creates a script user database on cloud_config info
        :param cloud_config: dictionary with
            'key-pairs': (optional) list of strings with the public key to be inserted to the default user
            'users': (optional) list of users to be inserted, each item is a dict with:
                'name': (mandatory) user name,
                'key-pairs': (optional) list of strings with the public key to be inserted to the user
            'user-data': (optional) can be a string with the text script to be passed directly to cloud-init,
                or a list of strings, each one contains a script to be passed, usually with a MIMEmultipart file
            'config-files': (optional). List of files to be transferred. Each item is a dict with:
                'dest': (mandatory) string with the destination absolute path
                'encoding': (optional, by default text). Can be one of:
                    'b64', 'base64', 'gz', 'gz+b64', 'gz+base64', 'gzip+b64', 'gzip+base64'
                'content' (mandatory): string with the content of the file
                'permissions': (optional) string with file permissions, typically octal notation '0644'
                'owner': (optional) file owner, string with the format 'owner:group'
            'boot-data-drive': boolean to indicate if user-data must be passed using a boot drive (hard disk)
        :return: config_drive, userdata. The first is a boolean or None, the second a string or None
        """
        config_drive = None
        userdata = None
        userdata_list = []

        # For more information, check https://cloudinit.readthedocs.io/en/latest/reference/merging.html
        # Basically, with this, we don't override the provider's cloud config
        merge_how = yaml.safe_dump(
            {
                "merge_how": [
                    {
                        "name": "list",
                        "settings": ["append", "recurse_dict", "recurse_list"],
                    },
                    {
                        "name": "dict",
                        "settings": ["no_replace", "recurse_list", "recurse_dict"],
                    },
                ]
            },
            indent=4,
            default_flow_style=False,
        )

        if isinstance(cloud_config, dict):
            if cloud_config.get("boot-data-drive") is not None:
                config_drive = cloud_config["boot-data-drive"]
            # If a config drive is needed, userdata is passed directly
            if config_drive:
                userdata = cloud_config.get("user-data")
            # If a config drive is not necessary, then we process userdata and
            # generate MIME multipart
            else:
                if cloud_config.get("user-data"):
                    if isinstance(cloud_config["user-data"], str):
                        userdata_list.append(
                            cloud_config["user-data"] + f"\n{merge_how}"
                        )
                    else:
                        for u in cloud_config["user-data"]:
                            userdata_list.append(u + f"\n{merge_how}")

                if (
                    cloud_config.get("config-files")
                    or cloud_config.get("users")
                    or cloud_config.get("key-pairs")
                ):
                    userdata_dict = {}

                    # default user
                    if cloud_config.get("key-pairs"):
                        userdata_dict["ssh-authorized-keys"] = cloud_config["key-pairs"]
                        userdata_dict["system_info"] = {
                            "default_user": {
                                "ssh_authorized_keys": cloud_config["key-pairs"],
                            }
                        }
                        userdata_dict["users"] = ["default"]

                    if cloud_config.get("users"):
                        if "users" not in userdata_dict:
                            userdata_dict["users"] = ["default"]

                        for user in cloud_config["users"]:
                            user_info = {
                                "name": user["name"],
                                "sudo": "ALL = (ALL)NOPASSWD:ALL",
                            }

                            if "user-info" in user:
                                user_info["gecos"] = user["user-info"]

                            if user.get("key-pairs"):
                                user_info["ssh-authorized-keys"] = user["key-pairs"]

                            userdata_dict["users"].append(user_info)

                    if cloud_config.get("config-files"):
                        userdata_dict["write_files"] = []
                        for file in cloud_config["config-files"]:
                            file_info = {
                                "path": file["dest"],
                                "content": file["content"],
                            }

                            if file.get("encoding"):
                                file_info["encoding"] = file["encoding"]

                            if file.get("permissions"):
                                file_info["permissions"] = file["permissions"]

                            if file.get("owner"):
                                file_info["owner"] = file["owner"]

                            userdata_dict["write_files"].append(file_info)

                    userdata_list.append(
                        "#cloud-config\n"
                        + yaml.safe_dump(
                            userdata_dict, indent=4, default_flow_style=False
                        )
                        + f"\n{merge_how}"
                    )
                userdata = self._create_mimemultipart(userdata_list)
                self.logger.debug("userdata: %s", userdata)
            # End if config_drive
        elif isinstance(cloud_config, str):
            userdata = cloud_config

        return config_drive, userdata

    def check_vim_connectivity(self):
        """Checks VIM can be reached and user credentials are ok.
        Returns None if success or raises VimConnConnectionException, VimConnAuthException, ...
        """
        # by default no checking until each connector implements it
        return None

    def get_tenant_list(self, filter_dict={}):
        """Obtain tenants of VIM
        filter_dict dictionary that can contain the following keys:
            name: filter by tenant name
            id: filter by tenant uuid/id
            <other VIM specific>
        Returns the tenant list of dictionaries, and empty list if no tenant match all the filers:
            [{'name':'<name>, 'id':'<id>, ...}, ...]
        """
        raise VimConnNotImplemented("Should have implemented this")

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
            'provider_network_profile': (optional) contains {segmentation-id: vlan, provider-network: vim_netowrk}
        Returns a tuple with the network identifier and created_items, or raises an exception on error
            created_items can be None or a dictionary where this method can include key-values that will be passed to
            the method delete_network. Can be used to store created segments, created l2gw connections, etc.
            Format is VimConnector dependent, but do not use nested dictionaries and a value of None should be the same
            as not present.
        """
        raise VimConnNotImplemented("Should have implemented this")

    def get_network_list(self, filter_dict={}):
        """Obtain tenant networks of VIM
        Params:
            'filter_dict' (optional) contains entries to return only networks that matches ALL entries:
                name: string  => returns only networks with this name
                id:   string  => returns networks with this VIM id, this imply returns one network at most
                shared: boolean >= returns only networks that are (or are not) shared
                tenant_id: sting => returns only networks that belong to this tenant/project
                ,#(not used yet) admin_state_up: boolean => returns only networks that are (or are not) in admin state
                    active
                #(not used yet) status: 'ACTIVE','ERROR',... => filter networks that are on this status
        Returns the network list of dictionaries. each dictionary contains:
            'id': (mandatory) VIM network id
            'name': (mandatory) VIM network name
            'status': (mandatory) can be 'ACTIVE', 'INACTIVE', 'DOWN', 'BUILD', 'ERROR', 'VIM_ERROR', 'OTHER'
            'network_type': (optional) can be 'vxlan', 'vlan' or 'flat'
            'segmentation_id': (optional) in case network_type is vlan or vxlan this field contains the segmentation id
            'error_msg': (optional) text that explains the ERROR status
            other VIM specific fields: (optional) whenever possible using the same naming of filter_dict param
        List can be empty if no network map the filter_dict. Raise an exception only upon VIM connectivity,
            authorization, or some other unspecific error
        """
        raise VimConnNotImplemented("Should have implemented this")

    def get_network(self, net_id):
        """Obtain network details from the 'net_id' VIM network
        Return a dict that contains:
            'id': (mandatory) VIM network id, that is, net_id
            'name': (mandatory) VIM network name
            'status': (mandatory) can be 'ACTIVE', 'INACTIVE', 'DOWN', 'BUILD', 'ERROR', 'VIM_ERROR', 'OTHER'
            'error_msg': (optional) text that explains the ERROR status
            other VIM specific fields: (optional) whenever possible using the same naming of filter_dict param
        Raises an exception upon error or when network is not found
        """
        raise VimConnNotImplemented("Should have implemented this")

    def delete_network(self, net_id, created_items=None):
        """
        Removes a tenant network from VIM and its associated elements
        :param net_id: VIM identifier of the network, provided by method new_network
        :param created_items: dictionary with extra items to be deleted. provided by method new_network
        Returns the network identifier or raises an exception upon error or when network is not found
        """
        raise VimConnNotImplemented("Should have implemented this")

    def refresh_nets_status(self, net_list):
        """Get the status of the networks
        Params:
            'net_list': a list with the VIM network id to be get the status
        Returns a dictionary with:
            'net_id':         #VIM id of this network
                status:     #Mandatory. Text with one of:
                    #  DELETED (not found at vim)
                    #  VIM_ERROR (Cannot connect to VIM, authentication problems, VIM response error, ...)
                    #  OTHER (Vim reported other status not understood)
                    #  ERROR (VIM indicates an ERROR status)
                    #  ACTIVE, INACTIVE, DOWN (admin down),
                    #  BUILD (on building process)
                error_msg:  #Text with VIM error message, if any. Or the VIM connection ERROR
                vim_info:   #Text with plain information obtained from vim (yaml.safe_dump)
            'net_id2': ...
        """
        raise VimConnNotImplemented("Should have implemented this")

    def get_flavor(self, flavor_id, flavor_name):
        """Obtain flavor details from the VIM
        Returns the flavor dict details {'id':<>, 'name':<>, other vim specific }
        Raises an exception upon error or if not found
        """
        raise VimConnNotImplemented("Should have implemented this")

    def get_flavor_id_from_data(self, flavor_dict):
        """Obtain flavor id that match the flavor description
        Params:
            'flavor_dict': dictionary that contains:
                'disk': main hard disk in GB
                'ram': meomry in MB
                'vcpus': number of virtual cpus
                #TODO: complete parameters for EPA
        Returns the flavor_id or raises a VimConnNotFoundException
        """
        raise VimConnNotImplemented("Should have implemented this")

    def new_flavor(self, flavor_data):
        """Adds a tenant flavor to VIM
            flavor_data contains a dictionary with information, keys:
                name: flavor name
                ram: memory (cloud type) in MBytes
                vpcus: cpus (cloud type)
                extended: EPA parameters
                  - numas: #items requested in same NUMA
                        memory: number of 1G huge pages memory
                        paired-threads|cores|threads: number of paired hyperthreads, complete cores OR individual
                            threads
                        interfaces: # passthrough(PT) or SRIOV interfaces attached to this numa
                          - name: interface name
                            dedicated: yes|no|yes:sriov;  for PT, SRIOV or only one SRIOV for the physical NIC
                            bandwidth: X Gbps; requested guarantee bandwidth
                            vpci: requested virtual PCI address
                disk: disk size
                is_public:
                 #TODO to concrete
        Returns the flavor identifier
        """
        raise VimConnNotImplemented("Should have implemented this")

    def delete_flavor(self, flavor_id):
        """Deletes a tenant flavor from VIM identify by its id
        Returns the used id or raise an exception
        """
        raise VimConnNotImplemented("Should have implemented this")

    def get_affinity_group(self, affinity_group_id):
        """Obtain affinity or anti affinity group details from the VIM
        Returns the flavor dict details {'id':<>, 'name':<>, other vim specific }
        Raises an exception upon error or if not found
        """
        raise VimConnNotImplemented("Should have implemented this")

    def new_affinity_group(self, affinity_group_data):
        """Adds an affinity or anti affinity group to VIM
            affinity_group_data contains a dictionary with information, keys:
                name: name in VIM for the affinity or anti-affinity group
                type: affinity or anti-affinity
                scope: Only nfvi-node allowed
        Returns the affinity or anti affinity group identifier
        """
        raise VimConnNotImplemented("Should have implemented this")

    def delete_affinity_group(self, affinity_group_id):
        """Deletes an affinity or anti affinity group from the VIM identified by its id
        Returns the used id or raise an exception
        """
        raise VimConnNotImplemented("Should have implemented this")

    def new_image(self, image_dict):
        """Adds a tenant image to VIM
        Returns the image id or raises an exception if failed
        """
        raise VimConnNotImplemented("Should have implemented this")

    def delete_image(self, image_id):
        """Deletes a tenant image from VIM
        Returns the image_id if image is deleted or raises an exception on error
        """
        raise VimConnNotImplemented("Should have implemented this")

    def get_image_id_from_path(self, path):
        """Get the image id from image path in the VIM database.
        Returns the image_id or raises a VimConnNotFoundException
        """
        raise VimConnNotImplemented("Should have implemented this")

    def get_image_list(self, filter_dict={}):
        """Obtain tenant images from VIM
        Filter_dict can be:
            name: image name
            id: image uuid
            checksum: image checksum
            location: image path
        Returns the image list of dictionaries:
            [{<the fields at Filter_dict plus some VIM specific>}, ...]
            List can be empty
        """
        raise VimConnNotImplemented("Should have implemented this")

    def new_vminstance(
        self,
        name,
        description,
        start,
        image_id,
        flavor_id,
        affinity_group_list,
        net_list,
        cloud_config=None,
        disk_list=None,
        availability_zone_index=None,
        availability_zone_list=None,
    ):
        """Adds a VM instance to VIM
        Params:
            'start': (boolean) indicates if VM must start or created in pause mode.
            'image_id','flavor_id': image and flavor VIM id to use for the VM
            affinity_group_list: list of affinity groups, each one is a dictionary.
                Ignore if empty.
            'net_list': list of interfaces, each one is a dictionary with:
                'name': (optional) name for the interface.
                'net_id': VIM network id where this interface must be connect to. Mandatory for type==virtual
                'vpci': (optional) virtual vPCI address to assign at the VM. Can be ignored depending on VIM
                    capabilities
                'model': (optional and only have sense for type==virtual) interface model: virtio, e1000, ...
                'mac_address': (optional) mac address to assign to this interface
                'ip_address': (optional) IP address to assign to this interface
                #TODO: CHECK if an optional 'vlan' parameter is needed for VIMs when type if VF and net_id is not
                    provided, the VLAN tag to be used. In case net_id is provided, the internal network vlan is used
                    for tagging VF
                'type': (mandatory) can be one of:
                    'virtual', in this case always connected to a network of type 'net_type=bridge'
                     'PCI-PASSTHROUGH' or 'PF' (passthrough): depending on VIM capabilities it can be connected to a
                        data/ptp network ot it
                           can created unconnected
                     'SR-IOV' or 'VF' (SRIOV with VLAN tag): same as PF for network connectivity.
                     'VFnotShared'(SRIOV without VLAN tag) same as PF for network connectivity. VF where no other VFs
                            are allocated on the same physical NIC
                'bw': (optional) only for PF/VF/VFnotShared. Minimal Bandwidth required for the interface in GBPS
                'port_security': (optional) If False it must avoid any traffic filtering at this interface. If missing
                                or True, it must apply the default VIM behaviour
                After execution the method will add the key:
                'vim_id': must be filled/added by this method with the VIM identifier generated by the VIM for this
                        interface. 'net_list' is modified
            'cloud_config': (optional) dictionary with:
                'key-pairs': (optional) list of strings with the public key to be inserted to the default user
                'users': (optional) list of users to be inserted, each item is a dict with:
                    'name': (mandatory) user name,
                    'key-pairs': (optional) list of strings with the public key to be inserted to the user
                'user-data': (optional) can be a string with the text script to be passed directly to cloud-init,
                    or a list of strings, each one contains a script to be passed, usually with a MIMEmultipart file
                'config-files': (optional). List of files to be transferred. Each item is a dict with:
                    'dest': (mandatory) string with the destination absolute path
                    'encoding': (optional, by default text). Can be one of:
                        'b64', 'base64', 'gz', 'gz+b64', 'gz+base64', 'gzip+b64', 'gzip+base64'
                    'content' (mandatory): string with the content of the file
                    'permissions': (optional) string with file permissions, typically octal notation '0644'
                    'owner': (optional) file owner, string with the format 'owner:group'
                'boot-data-drive': boolean to indicate if user-data must be passed using a boot drive (hard disk)
            'disk_list': (optional) list with additional disks to the VM. Each item is a dict with:
                'image_id': (optional). VIM id of an existing image. If not provided an empty disk must be mounted
                'size': (mandatory) string with the size of the disk in GB
            availability_zone_index: Index of availability_zone_list to use for this this VM. None if not AV required
            availability_zone_list: list of availability zones given by user in the VNFD descriptor.  Ignore if
                availability_zone_index is None
        Returns a tuple with the instance identifier and created_items or raises an exception on error
            created_items can be None or a dictionary where this method can include key-values that will be passed to
            the method delete_vminstance and action_vminstance. Can be used to store created ports, volumes, etc.
            Format is VimConnector dependent, but do not use nested dictionaries and a value of None should be the same
            as not present.
        """
        raise VimConnNotImplemented("Should have implemented this")

    def get_vminstance(self, vm_id):
        """Returns the VM instance information from VIM"""
        raise VimConnNotImplemented("Should have implemented this")

    def delete_vminstance(self, vm_id, created_items=None, volumes_to_hold=None):
        """
        Removes a VM instance from VIM and its associated elements
        :param vm_id: VIM identifier of the VM, provided by method new_vminstance
        :param created_items: dictionary with extra items to be deleted. provided by method new_vminstance and/or method
            action_vminstance
        :return: None or the same vm_id. Raises an exception on fail
        """
        raise VimConnNotImplemented("Should have implemented this")

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
                            #  BUILD (on building process), ERROR
                            #  ACTIVE:NoMgmtIP (Active but any of its interface has an IP address
                            #
                error_msg:  #Text with VIM error message, if any. Or the VIM connection ERROR
                vim_info:   #Text with plain information obtained from vim (yaml.safe_dump)
                interfaces: list with interface info. Each item a dictionary with:
                    vim_info:         #Text with plain information obtained from vim (yaml.safe_dump)
                    mac_address:      #Text format XX:XX:XX:XX:XX:XX
                    vim_net_id:       #network id where this interface is connected, if provided at creation
                    vim_interface_id: #interface/port VIM id
                    ip_address:       #null, or text with IPv4, IPv6 address
                    compute_node:     #identification of compute node where PF,VF interface is allocated
                    pci:              #PCI address of the NIC that hosts the PF,VF
                    vlan:             #physical VLAN used for VF
        """
        raise VimConnNotImplemented("Should have implemented this")

    def action_vminstance(self, vm_id, action_dict, created_items={}):
        """
        Send and action over a VM instance. Returns created_items if the action was successfully sent to the VIM.
        created_items is a dictionary with items that
        :param vm_id: VIM identifier of the VM, provided by method new_vminstance
        :param action_dict: dictionary with the action to perform
        :param created_items: provided by method new_vminstance is a dictionary with key-values that will be passed to
            the method delete_vminstance. Can be used to store created ports, volumes, etc. Format is VimConnector
            dependent, but do not use nested dictionaries and a value of None should be the same as not present. This
            method can modify this value
        :return: None, or a console dict
        """
        raise VimConnNotImplemented("Should have implemented this")

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
        raise VimConnNotImplemented("Should have implemented this")

    def inject_user_key(
        self, ip_addr=None, user=None, key=None, ro_key=None, password=None
    ):
        """
        Inject a ssh public key in a VM
        Params:
            ip_addr: ip address of the VM
            user: username (default-user) to enter in the VM
            key: public key to be injected in the VM
            ro_key: private key of the RO, used to enter in the VM if the password is not provided
            password: password of the user to enter in the VM
        The function doesn't return a value:
        """
        if not ip_addr or not user:
            raise VimConnNotSupportedException(
                "All parameters should be different from 'None'"
            )
        elif not ro_key and not password:
            raise VimConnNotSupportedException(
                "All parameters should be different from 'None'"
            )
        else:
            commands = {
                "mkdir -p ~/.ssh/",
                'echo "{}" >> ~/.ssh/authorized_keys'.format(key),
                "chmod 644 ~/.ssh/authorized_keys",
                "chmod 700 ~/.ssh/",
            }

            logging.basicConfig(
                format="%(asctime)s %(levelname)s %(name)s %(filename)s:%(lineno)s %(message)s"
            )
            logging.getLogger("paramiko").setLevel(logging.DEBUG)
            client = paramiko.SSHClient()

            try:
                if ro_key:
                    pkey = paramiko.RSAKey.from_private_key(StringIO(ro_key))
                else:
                    pkey = None

                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

                client.connect(
                    ip_addr,
                    username=user,
                    password=password,
                    pkey=pkey,
                    timeout=30,
                    auth_timeout=60,
                )

                for command in commands:
                    (i, o, e) = client.exec_command(command, timeout=30)
                    returncode = o.channel.recv_exit_status()
                    outerror = e.read()

                    if returncode != 0:
                        text = "run_command='{}' Error='{}'".format(command, outerror)
                        self.logger.debug(traceback.format_tb(e.__traceback__))
                        raise VimConnUnexpectedResponse(
                            "Cannot inject ssh key in VM: '{}'".format(text)
                        )
                        return
            except (
                socket.error,
                paramiko.AuthenticationException,
                paramiko.SSHException,
            ) as message:
                self.logger.debug(traceback.format_exc())
                raise VimConnUnexpectedResponse(
                    "Cannot inject ssh key in VM: '{}' - {}".format(
                        ip_addr, str(message)
                    )
                )
                return

    # Optional methods
    def new_tenant(self, tenant_name, tenant_description):
        """Adds a new tenant to VIM with this name and description, this is done using admin_url if provided
        "tenant_name": string max lenght 64
        "tenant_description": string max length 256
        returns the tenant identifier or raise exception
        """
        raise VimConnNotImplemented("Should have implemented this")

    def delete_tenant(self, tenant_id):
        """Delete a tenant from VIM
        tenant_id: returned VIM tenant_id on "new_tenant"
        Returns None on success. Raises and exception of failure. If tenant is not found raises VimConnNotFoundException
        """
        raise VimConnNotImplemented("Should have implemented this")

    def migrate_instance(self, vm_id, compute_host=None):
        """Migrate a vdu
        Params:
            vm_id: ID of an instance
            compute_host: Host to migrate the vdu to
        Returns the vm state or raises an exception upon error
        """
        raise VimConnNotImplemented("Should have implemented this")

    def resize_instance(self, vm_id, flavor_id=None):
        """
        resize a vdu
        param:
            vm_id: ID of an instance
            flavor_id: flavor_id to resize the vdu to
        """
        raise VimConnNotImplemented("Should have implemented this")
