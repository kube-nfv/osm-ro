# -*- coding: utf-8 -*-
##
# Copyright ETSI Contributors and Others.
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
osm-ro VIM connector plugin for Kube-VIM.

It implements the VimConnector interface defined by RO-plugin on top of the
Kube-VIM Vi-Vnfm (ETSI GS NFV-IFA 006) REST gateway, accessed through the
``kubevim-vivnfm-client`` package. The VIM account ``url`` is the gateway URL.

VIM account ``config`` keys:
    ssh_key: private key used by inject_user_key to reach the VMs
"""

import enum
import logging
import random
from typing import Any, List

from kubevim_vivnfm_client.api import vi_vnfm_api
from kubevim_vivnfm_client.api_client import ApiClient
from kubevim_vivnfm_client.configuration import Configuration
from kubevim_vivnfm_client.exceptions import (
    ApiException,
    BadRequestException,
    ConflictException,
    NotFoundException,
    UnauthorizedException,
)
from kubevim_vivnfm_client.models.identifier import Identifier
from kubevim_vivnfm_client.models.ip_address import IPAddress
from kubevim_vivnfm_client.models.ip_subnet_cidr import IPSubnetCIDR
from kubevim_vivnfm_client.models.ip_version import IPVersion
from kubevim_vivnfm_client.models.mac_address import MacAddress
from kubevim_vivnfm_client.models.metadata import Metadata
from kubevim_vivnfm_client.models.network_resource_type import NetworkResourceType
from kubevim_vivnfm_client.models.network_subnet_data import NetworkSubnetData
from kubevim_vivnfm_client.models.network_type import NetworkType
from kubevim_vivnfm_client.models.operational_state import OperationalState
from kubevim_vivnfm_client.models.pb_allocate_compute_request import (
    PbAllocateComputeRequest,
)
from kubevim_vivnfm_client.models.pb_allocate_network_request import (
    PbAllocateNetworkRequest,
)
from kubevim_vivnfm_client.models.pb_create_compute_flavour_request import (
    PbCreateComputeFlavourRequest,
)
from kubevim_vivnfm_client.models.resource_quantity import ResourceQuantity
from kubevim_vivnfm_client.models.type_virtual_nic import TypeVirtualNic
from kubevim_vivnfm_client.models.user_data import UserData
from kubevim_vivnfm_client.models.user_data_user_data_transportation_method import (
    UserDataUserDataTransportationMethod,
)
from kubevim_vivnfm_client.models.virtual_compute_flavour import VirtualComputeFlavour
from kubevim_vivnfm_client.models.virtual_cpu_data import VirtualCpuData
from kubevim_vivnfm_client.models.virtual_memory_data import VirtualMemoryData
from kubevim_vivnfm_client.models.virtual_network import VirtualNetwork
from kubevim_vivnfm_client.models.virtual_network_data import VirtualNetworkData
from kubevim_vivnfm_client.models.virtual_network_interface_data import (
    VirtualNetworkInterfaceData,
)
from kubevim_vivnfm_client.models.virtual_network_interface_ipam import (
    VirtualNetworkInterfaceIPAM,
)
from kubevim_vivnfm_client.models.virtual_storage_data import VirtualStorageData
from osm_ro_plugin import vimconn
import urllib3
import yaml


__author__ = "Dmytro Malovanyi"
__date__ = "2024-12-20"


def network_from_virtual_network_response(net: VirtualNetwork):
    res = {}
    res["id"] = net.network_resource_id.value
    res["name"] = net.network_resource_name
    state = net.operational_state
    if state == OperationalState.ENABLED:
        res["status"] = "ACTIVE"
    elif state == OperationalState.DISABLED:
        res["status"] = "INACTIVE"
    else:
        res["status"] = "OTHER"
        res["error_msg"] = f"Undefined state {state}"
    net_type = net.network_type
    if net_type == "NETWORK_TYPE_OVERLAY":
        res["network_type"] = "vxlan"
        # NOTE: kube-vim use ovn as a network soltion, while
        # ovn (might) use vxlan for the overlays it is lacks of the
        # specific "segmentation_id" for the network.
        res["segmentation_id"] = 0
    elif net_type == "NETWORK_TYPE_UNDERLAY":
        if net.segmentation_id is None or net.segmentation_id == "0":
            res["network_type"] = "flat"
        else:
            res["network_type"] = "vlan"
            res["segmentation_id"] = int(net.segmentation_id)
    elif net_type == "NETWORK_TYPE_SRIOV":
        res["network_type"] = "SR-IOV"
        if net.segmentation_id and int(net.segmentation_id) != 0:
            res["segmentation_id"] = int(net.segmentation_id)
    res["shared"] = net.is_shared
    res = {**res, **net.to_dict()}
    del res["connectedNetworks"]
    del res["networkResourceId"]
    del res["networkResourceName"]
    del res["networkType"]
    del res["operationalState"]
    return res


def convert_enums(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: convert_enums(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_enums(i) for i in obj]
    elif isinstance(obj, enum.Enum):
        return obj.value
    return obj


QUANTITY_SUFFIXES = {
    "": 1,
    "k": 10**3,
    "M": 10**6,
    "G": 10**9,
    "T": 10**12,
    "P": 10**15,
    "E": 10**18,
    "Ki": 2**10,
    "Mi": 2**20,
    "Gi": 2**30,
    "Ti": 2**40,
    "Pi": 2**50,
    "Ei": 2**60,
}


def quantity_to_bytes(quantity: str) -> float:
    """Converts a Kubernetes quantity string (e.g. "2048M", "10Gi") to bytes."""
    number = quantity.rstrip("kMGTPEi")
    suffix = quantity[len(number) :]
    try:
        return float(number) * QUANTITY_SUFFIXES[suffix]
    except (KeyError, ValueError):
        raise vimconn.VimConnUnexpectedResponse(f"invalid quantity: {quantity}")


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
        super().__init__(
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
            persistent_info,
        )
        self.logger = logging.getLogger("ro.vim.kubevim")
        self.configuration = Configuration(host=url)
        if log_level:
            self.logger.setLevel(getattr(logging, log_level))

    def check_vim_connectivity(self):
        self.logger.debug("Check VIM connectivity")
        with ApiClient(self.configuration) as api_client:
            api_instance = vi_vnfm_api.ViVnfmApi(api_client)
            try:
                api_instance.vi_vnfm_query_compute_flavour()
            except (ApiException, urllib3.exceptions.HTTPError) as ex:
                self._format_exception(ex)

    def new_network(
        self,
        net_name,
        net_type,
        ip_profile=None,
        shared=False,
        provider_network_profile=None,
    ):
        self.logger.debug(
            "Network create request: name=%s, type=%s, ip_profile=%s, shared=%s, provider_network_profile=%s",
            net_name,
            net_type,
            ip_profile,
            shared,
            provider_network_profile,
        )
        req = PbAllocateNetworkRequest(
            networkResourceType=NetworkResourceType("NETWORK")
        )

        req.network_resource_name = net_name
        bandwidth = 100  # Mbps
        net = VirtualNetworkData(bandwidth=bandwidth)
        net.is_shared = shared
        if not ip_profile:
            ip_profile = {}

        if not ip_profile.get("subnet_address"):
            # Fake subnet is required
            subnet_rand = random.SystemRandom().randint(0, 255)
            ip_profile["subnet_address"] = "192.168.{}.0/24".format(subnet_rand)
        if "ip_version" not in ip_profile:
            ip_profile["ip_version"] = "IPv4"

        subnet = NetworkSubnetData()
        if ip_profile["ip_version"] == "IPv4":
            subnet.ip_version = IPVersion("IPV4")
        elif ip_profile["ip_version"] == "IPv6":
            subnet.ip_version = IPVersion("IPV6")
        if ip_profile.get("gateway_address"):
            subnet.gateway_ip = IPAddress(ip=ip_profile["gateway_address"])
        subnet.cidr = IPSubnetCIDR(cidr=ip_profile["subnet_address"])

        if "dhcp_enabled" in ip_profile:
            subnet.is_dhcp_enabled = (
                False
                if ip_profile["dhcp_enabled"] == "false"
                or ip_profile["dhcp_enabled"] is False
                else True
            )
        else:
            subnet.is_dhcp_enabled = True

        # TODO: Add dhcp pool
        if net_type in ["data", "ptp"] or provider_network_profile:
            if provider_network_profile is None:
                raise vimconn.VimConnNotSupportedException(
                    f"provider network should be defined for the {net_type} network type"
                )
            physical_network = provider_network_profile.get(
                "physical-network"
            ) or provider_network_profile.get("provider_network")
            seg_id = provider_network_profile.get(
                "segmentation-id"
            ) or provider_network_profile.get("segmentation_id")
            if provider_network_profile.get("network-type") == "sriov":
                net.network_type = NetworkType("NETWORK_TYPE_SRIOV")
                net.provider_network = physical_network
                if seg_id and str(seg_id) != "0":
                    net.segmentation_id = str(seg_id)
            else:
                net.network_type = NetworkType("NETWORK_TYPE_UNDERLAY")
                net.provider_network = physical_network
                if seg_id and str(seg_id) != "0":
                    net.segmentation_id = str(seg_id)
                if subnet:
                    net.layer3_attributes = [subnet]
        else:
            net.network_type = NetworkType("NETWORK_TYPE_OVERLAY")
            if subnet:
                net.layer3_attributes = [subnet]

        req.type_network_data = net
        with ApiClient(self.configuration) as api_client:
            api_instance = vi_vnfm_api.ViVnfmApi(api_client)
            try:
                api_response = (
                    api_instance.vi_vnfm_allocate_virtualised_network_resource(body=req)
                )
                if api_response is None or api_response.network_data is None:
                    raise vimconn.VimConnUnexpectedResponse("received empty response")
                net_id = api_response.network_data.network_resource_id.value
                return net_id, {}
            except (ApiException, urllib3.exceptions.HTTPError) as ex:
                self._format_exception(ex)

    def get_network_list(self, filter_dict=None):
        self.logger.debug("Get Networks. Filter dict: %s", filter_dict)
        with ApiClient(self.configuration) as api_client:
            api_instance = vi_vnfm_api.ViVnfmApi(api_client)
            query_filter = ""
            if filter_dict:
                query_filter = "filter="
                for filter_name, filter_val in filter_dict.items():
                    if filter_name == "name":
                        query_filter += f"(eq,networkResourceName,{filter_val});"
                        continue
                    if filter_name == "id":
                        query_filter += f"(eq,networkResourceId/value,{filter_val});"
                        continue
                    if filter_name == "shared":
                        query_filter += (
                            f'(eq,isShared,{"true" if filter_val else "false"});'
                        )
                        continue
                    raise vimconn.VimConnNotSupportedException(
                        f"get network filter {filter_name} is not supported"
                    )
                query_filter = query_filter[:-1]
            try:
                api_response = api_instance.vi_vnfm_query_virtualised_network_resource(
                    "NETWORK", query_filter
                )
                res = []
                if api_response is None:
                    raise vimconn.VimConnUnexpectedResponse("response can't be empty")
                # query_network_result can be None when no networks match the filter
                if api_response.query_network_result is not None:
                    for net in api_response.query_network_result:
                        res.append(network_from_virtual_network_response(net))
                return res
            except (ApiException, urllib3.exceptions.HTTPError) as ex:
                self._format_exception(ex)

    def get_network(self, net_id):
        self.logger.debug("Network %s get request", net_id)
        with ApiClient(self.configuration) as api_client:
            api_instance = vi_vnfm_api.ViVnfmApi(api_client)
            query_filter = f"filter=(eq,networkResourceId/value,{net_id})"
            try:
                api_response = api_instance.vi_vnfm_query_virtualised_network_resource(
                    "NETWORK", query_filter
                )
                if api_response is None:
                    raise vimconn.VimConnUnexpectedResponse("received empty response")
                # query_network_result can be None when no networks match the filter
                if (
                    api_response.query_network_result is None
                    or len(api_response.query_network_result) == 0
                ):
                    raise vimconn.VimConnNotFoundException(
                        f"network with id {net_id} not found"
                    )
                net_data_lst = api_response.query_network_result
                if len(net_data_lst) > 1:
                    raise vimconn.VimConnUnexpectedResponse(
                        f"More that one network found by the id {net_id}"
                    )
                net_data = net_data_lst[0]
                return network_from_virtual_network_response(net_data)
            except (ApiException, urllib3.exceptions.HTTPError) as ex:
                self._format_exception(ex)

    def delete_network(self, net_id, created_items=None):
        with ApiClient(self.configuration) as api_client:
            api_instance = vi_vnfm_api.ViVnfmApi(api_client)
            try:
                api_response = (
                    api_instance.vi_vnfm_terminate_virtualised_network_resource(net_id)
                )
                if api_response is None or api_response.network_resource_id is None:
                    raise vimconn.VimConnUnexpectedResponse("received empty response")
                return api_response.network_resource_id.value
            except (ApiException, urllib3.exceptions.HTTPError) as ex:
                self._format_exception(ex)

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
        res = {}
        try:
            nets = self.get_network_list()
            by_id = {net["id"]: net for net in nets}
            for net_id in net_list:
                if net_id in by_id:
                    net = by_id[net_id]
                    res[net_id] = {
                        "status": net["status"],
                        "vim_info": yaml.safe_dump(net),
                    }
                else:
                    res[net_id] = {"status": "DELETED"}
        except vimconn.VimConnException as ex:
            for net_id in net_list:
                res[net_id] = {"status": "VIM_ERROR", "error_msg": ex.__str__()}
        return res

    def get_flavor(self, flavor_id=None, flavor_name=None):
        self.logger.debug(
            "Flavour id: %s, name: %s get request", flavor_id, flavor_name
        )
        if flavor_id is None:
            raise vimconn.VimConnNotSupportedException(
                "Get flavor by name is not supported"
            )
        with ApiClient(self.configuration) as api_client:
            api_instance = vi_vnfm_api.ViVnfmApi(api_client)
            query_filter = f"filter=(eq,flavourId/value,{flavor_id})"
            try:
                api_response = api_instance.vi_vnfm_query_compute_flavour(
                    query_compute_flavour_filter_value=query_filter
                )
                # flavours can be None when no flavours match the filter
                if (
                    api_response is None
                    or api_response.flavours is None
                    or len(api_response.flavours) == 0
                ):
                    raise vimconn.VimConnNotFoundException(
                        f"failed to find flavor with id: {flavor_id}"
                    )
                flavors = api_response.flavours
                if len(flavors) > 1:
                    raise vimconn.VimConnUnexpectedResponse(
                        f"more that one flavor found with id: {flavor_id}"
                    )
                flavor = flavors[0]
                if flavor.flavour_id is None:
                    raise vimconn.VimConnUnexpectedResponse(
                        "flavor id can't be empty in response"
                    )
                rsp_flavor_id = flavor.flavour_id.value

                flavNameAnn = "flavour.kubevim.kubenfv.io/attached-name"
                if (
                    flavor.metadata is None
                    or flavor.metadata.fields is None
                    or flavNameAnn not in flavor.metadata.fields
                ):
                    raise vimconn.VimConnUnexpectedResponse(
                        f"flavor missing metadata fields: {flavor_id}"
                    )

                boot_storage = [s for s in flavor.storage_attributes or [] if s.is_boot]
                if not boot_storage:
                    raise vimconn.VimConnUnexpectedResponse(
                        f"flavor missing boot storage: {flavor_id}"
                    )

                # Same units new_flavor writes: ram in MB (M), disk in GiB (Gi)
                resp = {
                    "id": rsp_flavor_id,
                    "name": flavor.metadata.fields[flavNameAnn],
                    "ram": round(
                        quantity_to_bytes(flavor.virtual_memory.virtual_mem_size.string)
                        / 10**6
                    ),
                    "vcpus": flavor.virtual_cpu.num_virtual_cpu,
                    "disk": round(
                        quantity_to_bytes(boot_storage[0].size_of_storage.string)
                        / 2**30
                    ),
                }
                return resp
            except (ApiException, urllib3.exceptions.HTTPError) as e:
                self._format_exception(e)

    def new_flavor(self, flavor_data):
        self.logger.debug("new flavour creation with data %s requested", flavor_data)
        with ApiClient(self.configuration) as api_client:
            api_instance = vi_vnfm_api.ViVnfmApi(api_client=api_client)

            mem = VirtualMemoryData(
                virtualMemSize=ResourceQuantity(string=f'{flavor_data["ram"]}M')
            )
            cpu = VirtualCpuData(numVirtualCpu=flavor_data["vcpus"])
            storage = [
                VirtualStorageData(
                    typeOfStorage="volume",
                    sizeOfStorage=ResourceQuantity(string=f'{flavor_data["disk"]}Gi'),
                    isBoot=True,
                )
            ]

            flavor = VirtualComputeFlavour(
                virtualMemory=mem, virtualCpu=cpu, storageAttributes=storage
            )
            metadata = Metadata(
                fields={"flavour.kubevim.kubenfv.io/attached-name": flavor_data["name"]}
            )
            body = PbCreateComputeFlavourRequest(flavour=flavor, metaData=metadata)
            try:
                api_response = api_instance.vi_vnfm_create_compute_flavour(body)
                flavor_id = api_response.flavour_id
                if flavor_id is None or flavor_id.value is None:
                    raise vimconn.VimConnUnexpectedResponse(
                        "flavor_id in flavor creation response can't be empty"
                    )
                flavor_id = flavor_id.value
                return flavor_id
            except (ApiException, urllib3.exceptions.HTTPError) as e:
                self._format_exception(e)

    def delete_flavor(self, flavor_id):
        self.logger.debug("Flavour %s delete request", flavor_id)
        with ApiClient(self.configuration) as api_client:
            api_instance = vi_vnfm_api.ViVnfmApi(api_client)
            try:
                api_instance.vi_vnfm_delete_compute_flavour(
                    compute_flavour_id_value=flavor_id
                )
                return flavor_id
            except (ApiException, urllib3.exceptions.HTTPError) as ex:
                self._format_exception(ex)

    def get_flavor_id_from_data(self, flavor_dict):
        with ApiClient(self.configuration) as api_client:
            api_instance = vi_vnfm_api.ViVnfmApi(api_client)
            query_filter = f'filter=(eq,virtualMemory/virtualMemSize,{flavor_dict["ram"]}M);(eq,virtualCpu/numVirtualCpu,{flavor_dict["vcpus"]});(eq,storageAttributes/sizeOfStorage,{flavor_dict["disk"]}Gi)'
            try:
                api_response = api_instance.vi_vnfm_query_compute_flavour(
                    query_compute_flavour_filter_value=query_filter
                )
                if api_response.flavours is None or len(api_response.flavours) == 0:
                    raise vimconn.VimConnNotFoundException(
                        "flavor with ram={}  cpu={} disk={} {} not found".format(
                            flavor_dict["ram"],
                            flavor_dict["vcpus"],
                            flavor_dict["disk"],
                            "and extended" if flavor_dict.get("extended") else "",
                        )
                    )
                flavor = api_response.flavours[0]
                if flavor.flavour_id is None or flavor.flavour_id.value is None:
                    raise vimconn.VimConnUnexpectedResponse(
                        "flavor_id can't be empty in flavor query response"
                    )
                return flavor.flavour_id.value
            except (ApiException, urllib3.exceptions.HTTPError) as e:
                self._format_exception(e)

    def get_image_list(self, filter_dict={}):
        img_filter = ""
        if filter_dict is not None and len(filter_dict) != 0:
            img_filter = "filter="
        for filter_name, filter_val in (filter_dict or {}).items():
            if filter_name == "id":
                img_filter += f"(eq,softwareImageId/value,{filter_val});"
            elif filter_name == "name":
                img_filter += f"(eq,name,{filter_val});"
            elif filter_name == "location":
                raise vimconn.VimConnNotImplemented(
                    "list images by the location is not supported yet"
                )
            elif filter_name == "checksum":
                raise vimconn.VimConnNotImplemented(
                    "list images by the checksum is not supported yet"
                )
        # remove trailing ;
        img_filter = img_filter[:-1]
        self.logger.debug(
            "Image list request: %s. Filter query: %s", filter_dict, img_filter
        )
        with ApiClient(self.configuration) as api_client:
            api_instance = vi_vnfm_api.ViVnfmApi(api_client)
            try:
                api_response = api_instance.vi_vnfm_query_images(img_filter)
                resp = []
                if api_response is None:
                    raise vimconn.VimConnUnexpectedResponse("received empty response")
                # software_images_information can be None when no images match the filter
                if api_response.software_images_information is None:
                    return resp
                for img in api_response.software_images_information:
                    imgId = img.software_image_id.value
                    img_dict = img.to_dict()
                    img_dict["id"] = imgId
                    img_dict["name"] = img.name
                    img_dict["checksum"] = "none"
                    location_key = "image.kubevim.kubenfv.io/source-url"
                    if (
                        img.metadata
                        and img.metadata.fields
                        and location_key in img.metadata.fields
                    ):
                        img_dict["location"] = img.metadata.fields[location_key]
                    else:
                        img_dict["location"] = "None"
                    resp.append(img_dict)
                return resp
            except (ApiException, urllib3.exceptions.HTTPError) as e:
                self._format_exception(e)

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
        security_group_name=None,
    ):
        self.logger.debug(
            "Compute create request: name=%s, image_id=%s, flavor_id=%s, net_list=%s",
            name,
            image_id,
            flavor_id,
            net_list,
        )
        # Interfaces are matched back to net_list by net_id, so it must be unique
        net_ids = [net["net_id"] for net in net_list if net.get("net_id")]
        if len(net_ids) != len(set(net_ids)):
            raise vimconn.VimConnNotSupportedException(
                "more than one interface on the same network is not supported"
            )
        req = PbAllocateComputeRequest(
            computeFlavourId=Identifier(value=flavor_id),
            computeName=name,
            vcImageId=Identifier(value=image_id),
        )

        req.interface_data = []
        req.interface_ipam = []
        for net in net_list:
            nic_type = None
            if net["type"] == "virtual":
                nic_type = TypeVirtualNic.TYPE_VIRTUAL_NIC_BRIDGE
            elif net["type"] in ("PCI-PASSTHROUGH", "PCI_PASSTHROUGH", "PF"):
                raise vimconn.VimConnNotSupportedException(
                    f'PCI passthrough interface ({net["type"]}) is not supported by Kube-VIM'
                )
            # TODO: Differentiate shared and not shared VF's
            elif (
                net["type"] == "SR-IOV"
                or net["type"] == "VF"
                or net["type"] == "VFnotShared"
            ):
                nic_type = TypeVirtualNic.TYPE_VIRTUAL_NIC_SRIOV
            else:
                raise vimconn.VimConnNotSupportedException(
                    f'unknown network type: {net["type"]}'
                )

            net_data = VirtualNetworkInterfaceData(typeVirtualNic=nic_type)

            if "bw" in net:
                net_data.bandwidth = int(net["bw"]) * 1000
            if "net_id" in net:
                net_data.network_id = Identifier(value=net["net_id"])

            net_ipam = VirtualNetworkInterfaceIPAM(networkId=net_data.network_id)
            if "ip_address" in net:
                net_ipam.ip_address = IPAddress(ip=net["ip_address"])
            if "mac_address" in net:
                net_ipam.mac_address = MacAddress(mac=net["mac_address"])

            if "ip_address" not in net:
                net_meta = Metadata()
                net_meta.fields = {
                    "compute.kubevim.kubenfv.io/network.subnet.assignment": "random",
                }
                net_data.metadata = net_meta

            req.interface_data.append(net_data)
            req.interface_ipam.append(net_ipam)

        _, userdata = self._create_user_data(cloud_config)
        if userdata:
            req.user_data = UserData(
                content=str(userdata),
                method=UserDataUserDataTransportationMethod.NO_CLOUD,
            )
        with ApiClient(self.configuration) as api_client:
            api_instance = vi_vnfm_api.ViVnfmApi(api_client)
            try:
                vm_data = api_instance.vi_vnfm_allocate_virtualised_compute_resource(
                    body=req
                )
                vm_id = vm_data.compute_data.compute_id.value
                for iface in vm_data.compute_data.virtual_network_interface:
                    ifaceMeta = iface.metadata
                    if ifaceMeta is None or ifaceMeta.fields is None:
                        continue
                    # Skip the KubeVirt-managed PodNetwork interface (ovn-default,
                    # tagged with network.vm.kubevirt.io/management=true by kube-vim).
                    # All Multus-attached interfaces (no such label) must be processed
                    # so their vim_id gets recorded; otherwise ns_thread raises KeyError
                    # on net_list iface["vim_id"] and the whole VDU CREATE task is
                    # marked FAILED even though kube-vim already created the VM.
                    mgmtIfaceLabel = "network.vm.kubevirt.io/management"
                    if (
                        mgmtIfaceLabel in ifaceMeta.fields
                        and ifaceMeta.fields[mgmtIfaceLabel] == "true"
                    ):
                        continue
                    if iface.network_id is None:
                        continue
                    # Try to find iface with same networkid
                    ifaceNet = iface.network_id.value

                    for cfgIface in net_list:
                        if cfgIface["net_id"] == ifaceNet:
                            # Update vim_id from response
                            cfgIface["vim_id"] = iface.resource_id.value
                            self.logger.debug(
                                "Update iface vim_id: %s for network %s",
                                cfgIface["vim_id"],
                                ifaceNet,
                            )
                return vm_id, {}
            except (ApiException, urllib3.exceptions.HTTPError) as ex:
                self._format_exception(ex)

    def get_vminstance(self, vm_id):
        self.logger.debug("Compute %s get request", vm_id)
        with ApiClient(self.configuration) as api_client:
            api_instance = vi_vnfm_api.ViVnfmApi(api_client)
            query_filter = f"filter=(eq,computeId/value,{vm_id})"
            try:
                api_response = api_instance.vi_vnfm_query_virtualised_compute_resource(
                    query_compute_filter_value=query_filter
                )
                # query_result can be None when no VMs match the filter
                if (
                    api_response.query_result is None
                    or len(api_response.query_result) == 0
                ):
                    raise vimconn.VimConnNotFoundException(
                        f"not found vm with id {vm_id}"
                    )
                if len(api_response.query_result) > 1:
                    raise vimconn.VimConnUnexpectedResponse(
                        f"more than one vm was found with id {vm_id}"
                    )
                vm_info = api_response.query_result[0]
                return convert_enums(vm_info.model_dump(by_alias=True))
            except (ApiException, urllib3.exceptions.HTTPError) as ex:
                self._format_exception(ex)

    def delete_vminstance(self, vm_id, created_items=None, volumes_to_hold=None):
        # Currently only vm_id is enough
        self.logger.debug("Compute %s delete request", vm_id)
        with ApiClient(self.configuration) as api_client:
            api_instance = vi_vnfm_api.ViVnfmApi(api_client)
            try:
                api_response = (
                    api_instance.vi_vnfm_terminate_virtualised_compute_resource(
                        compute_id_value=vm_id
                    )
                )
                if api_response.compute_id.value != vm_id:
                    raise vimconn.VimConnUnexpectedResponse(
                        f"delete vm id {api_response.compute_id.value} mismatch input id {vm_id}"
                    )
                return vm_id
            except (ApiException, urllib3.exceptions.HTTPError) as ex:
                self._format_exception(ex)

    def refresh_vms_status(self, vm_list: List):
        res = dict()
        for vm_id in vm_list:
            try:
                vm_info = self.get_vminstance(vm_id)
            except vimconn.VimConnNotFoundException:
                res[vm_id] = {
                    "status": "DELETED",
                    "error_msg": f"vm {vm_id} doesn't exists",
                }
                continue
            except Exception as ex:
                res[vm_id] = {
                    "status": "VIM_ERROR",
                    "error_msg": str(ex),
                }
                continue
            running_state = vm_info["runningState"]
            err_msg = ""

            if running_state == "FAILED":
                metadata = vm_info["metadata"]["fields"]
                reason_meta_label = "status.vmi.kubevirt.io/reason"
                err_msg = "unknown"
                if reason_meta_label in metadata:
                    err_msg = metadata[reason_meta_label]
                res[vm_id] = {
                    "status": "ERROR",
                    "error_msg": err_msg,
                }
                continue

            status_map = {
                "RUNNING": "ACTIVE",
                "PAUSED": "PAUSED",
                "STARTING": "BUILD",
                "SUSPENDED": "SUSPENDED",
                "STOPPED": "INACTIVE",
                "TERMINATING": "INACTIVE",
            }
            vm_status = status_map.get(running_state, "OTHER")
            if vm_status == "OTHER":
                err_msg = f"status is {running_state}"

            vim_info = yaml.safe_dump(vm_info)
            interfaces = []
            for iface in vm_info["virtualNetworkInterface"]:
                ifaceMeta = iface["metadata"]["fields"]
                ifaceReadyLabel = "interface.vm.kubevirt.io/ready"
                if (
                    ifaceReadyLabel not in ifaceMeta
                    or ifaceMeta[ifaceReadyLabel] == "false"
                ):
                    # Need to think if Active:NoMgmtIp is better suited here
                    vm_status = "BUILD"
                    continue
                iface_dict = dict()
                iface_dict["vim_info"] = yaml.safe_dump(iface)
                iface_dict["mac_address"] = iface["macAddress"]["mac"]
                if len(iface["ipAddress"]) > 0:
                    iface_dict["ip_address"] = iface["ipAddress"][0]["ip"]
                else:
                    iface_dict["ip_address"] = None
                if iface["networkId"] is not None:
                    iface_dict["vim_net_id"] = iface["networkId"]["value"]
                elif (
                    iface["metadata"]["fields"]["network.vm.kubevirt.io/management"]
                    == "true"
                ):
                    iface_dict["vim_net_id"] = "management"
                iface_dict["vim_interface_id"] = iface["resourceId"]["value"]
                iface_dict["compute_node"] = vm_info["hostId"]["value"]
                # TODO: pci and vlan
                interfaces.append(iface_dict)

            res[vm_id] = {
                "status": vm_status,
                "error_msg": err_msg,
                "vim_info": vim_info,
                "interfaces": interfaces,
            }
        return res

    def action_vminstance(self, vm_id, action_dict, created_items={}):
        raise vimconn.VimConnNotSupportedException(
            "vm actions are not supported by Kube-VIM yet"
        )

    def inject_user_key(
        self, ip_addr=None, user=None, key=None, ro_key=None, password=None
    ):
        if self.config.get("ssh_key"):
            ro_key = self.config.get("ssh_key")

        return super().inject_user_key(
            ip_addr=ip_addr, user=user, key=key, ro_key=ro_key, password=password
        )

    def _format_exception(self, exception: ApiException):
        """Raises a vimconn exception if the requests to the api is not OK"""
        if isinstance(exception, UnauthorizedException):
            raise vimconn.VimConnAuthException(exception)
        elif isinstance(exception, NotFoundException):
            raise vimconn.VimConnNotFoundException(exception)
        elif isinstance(exception, ConflictException):
            raise vimconn.VimConnConflictException(exception)
        elif isinstance(exception, BadRequestException):
            raise vimconn.VimConnException(exception)
        else:
            raise vimconn.VimConnConnectionException(exception)
