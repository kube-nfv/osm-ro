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
Kube-VIM v1 REST API (ETSI GS NFV-SOL 013 conventions over the IFA 005/006
information model), accessed through the ``kubevim-client`` package. The VIM
account ``url`` is the gateway URL.

VIM account ``config`` keys:
    management_network_name: existing Kube-VIM network that VLDs marked
        mgmt-network are mapped onto instead of creating one, typically the
        management network kube-vim provisions (read by NG-RO, which looks it up
        through get_network_list)
    management_network_id: the same by network ID; takes precedence over the name
    ssh_key: private key used by inject_user_key to reach the VMs
    token_url: OAuth 2.0 token endpoint. When set, or when issuer is set, requests
        carry a client-credentials access token; the VIM account user and password
        are the client ID and secret
    issuer: OIDC issuer whose discovery document gives the token endpoint, used when
        token_url is not set
    scope: optional scope for the token request
    ca_cert: CA bundle for the gateway and the token endpoint (NG-RO writes
        ca_cert_content to this file)
    insecure: skip TLS certificate verification; exclusive with ca_cert

VLD ``provider-network`` instantiation parameters:
    physical-network: the Kube-OVN provider network, optionally followed by
        ``/<pool>``, the SR-IOV virtual function pool on its uplink (a pool
        without a domain gets ``openshift.io/``), e.g. ``mx5p0/mlx_vf_pf0_vfio``.
        A network with a pool takes SR-IOV interfaces, and bridged ones when it
        also has a subnet
    segmentation-id: the VLAN ID; absent or 0 gives a FLAT network
    network-type: ``sriov`` creates the network without a subnet, so it takes
        SR-IOV interfaces only; it needs a pool
"""

import base64
import enum
import json
import logging
import random
import time
from typing import Any, List
from urllib.parse import quote_plus

from kubevim_client.api.compute_service_api import ComputeServiceApi
from kubevim_client.api.flavour_service_api import FlavourServiceApi
from kubevim_client.api.image_service_api import ImageServiceApi
from kubevim_client.api.network_service_api import NetworkServiceApi
from kubevim_client.api_client import ApiClient
from kubevim_client.configuration import Configuration
from kubevim_client.exceptions import (
    ApiException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
    UnauthorizedException,
)
from kubevim_client.models.compute import Compute
from kubevim_client.models.compute_running_state import ComputeRunningState
from kubevim_client.models.create_compute_request import CreateComputeRequest
from kubevim_client.models.create_flavour_request import CreateFlavourRequest
from kubevim_client.models.create_network_request import CreateNetworkRequest
from kubevim_client.models.flavour import Flavour
from kubevim_client.models.image_source_http import ImageSourceHttp
from kubevim_client.models.ip_assignment import IpAssignment
from kubevim_client.models.ip_version import IpVersion
from kubevim_client.models.network import Network
from kubevim_client.models.network_interface_data import NetworkInterfaceData
from kubevim_client.models.network_type import NetworkType
from kubevim_client.models.operational_state import OperationalState
from kubevim_client.models.sriov_settings import SriovSettings
from kubevim_client.models.subnet_data import SubnetData
from kubevim_client.models.type_of_storage import TypeOfStorage
from kubevim_client.models.type_virtual_nic import TypeVirtualNic
from kubevim_client.models.user_data import UserData
from kubevim_client.models.user_data_transportation_method import (
    UserDataTransportationMethod,
)
from kubevim_client.models.virtual_cpu_data import VirtualCpuData
from kubevim_client.models.virtual_memory_data import VirtualMemoryData
from kubevim_client.models.virtual_storage_data import VirtualStorageData
from osm_ro_plugin import vimconn
import urllib3
import yaml


__author__ = "Dmytro Malovanyi"
__date__ = "2024-12-20"

# A pool name without a domain belongs to the SR-IOV network operator's default domain
DEFAULT_POOL_DOMAIN = "openshift.io/"
# ProblemDetails type of a request field Kube-VIM does not support
UNSUPPORTED_FIELD_PROBLEM = "https://kubevim.kubenfv.io/problems/unsupported-field"


def network_from_kubevim(net: Network):
    res = {"id": net.network_id, "name": net.network_name}
    state = net.operational_state
    if state == OperationalState.OPERATIONAL_STATE_ENABLED:
        res["status"] = "ACTIVE"
    elif state == OperationalState.OPERATIONAL_STATE_DISABLED:
        res["status"] = "INACTIVE"
    else:
        res["status"] = "OTHER"
        res["error_msg"] = f"Undefined state {state}"
    net_type = net.network_type
    if net_type == NetworkType.NETWORK_TYPE_GENEVE:
        res["network_type"] = "vxlan"
        # Kube-OVN overlays have no segmentation ID of their own.
        res["segmentation_id"] = 0
    elif net_type == NetworkType.NETWORK_TYPE_VLAN:
        res["network_type"] = "vlan"
        res["segmentation_id"] = net.segmentation_id
    elif net_type == NetworkType.NETWORK_TYPE_FLAT:
        res["network_type"] = "flat"
    res["shared"] = False
    res = {**res, **convert_enums(net.model_dump(by_alias=True, exclude_none=True))}
    for key in ("networkId", "networkName", "networkType", "operationalState"):
        res.pop(key, None)
    return res


def convert_enums(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: convert_enums(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_enums(i) for i in obj]
    elif isinstance(obj, enum.Enum):
        return obj.value
    return obj


def filter_value(value) -> str:
    """Quotes a value for a SOL 013 filter expression."""
    return "'" + str(value).replace("'", "''") + "'"


def split_physical_network(physical_network: str):
    """Splits '<provider network>[/<pool>]' into the provider network and the pool or None."""
    provider, _, pool = physical_network.partition("/")
    if not pool:
        return provider, None
    if "/" not in pool:
        pool = DEFAULT_POOL_DOMAIN + pool
    return provider, pool


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


# Seconds before expiry at which a cached access token is replaced
TOKEN_REFRESH_MARGIN = 30


class _AuthApiClient(ApiClient):
    """ApiClient that sends the connector's bearer token and retries a 401 once."""

    def __init__(self, configuration, connector):
        super().__init__(configuration)
        self._connector = connector
        self.set_default_header("Authorization", f"Bearer {connector._access_token()}")

    def call_api(
        self,
        method,
        url,
        header_params=None,
        body=None,
        post_params=None,
        _request_timeout=None,
    ):
        response = super().call_api(
            method, url, header_params, body, post_params, _request_timeout
        )
        if response.status != 401:
            return response
        self._connector.logger.debug("Access token rejected, fetching a new one")
        self._connector._token = None
        bearer = f"Bearer {self._connector._access_token()}"
        self.set_default_header("Authorization", bearer)
        header_params = {**(header_params or {}), "Authorization": bearer}
        return super().call_api(
            method, url, header_params, body, post_params, _request_timeout
        )


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
        if log_level:
            self.logger.setLevel(getattr(logging, log_level))

        insecure = self.config.get("insecure")
        ca_cert = self.config.get("ca_cert")
        if insecure and ca_cert:
            raise vimconn.VimConnException(
                "options insecure and ca_cert are mutually exclusive"
            )
        self.configuration = Configuration(host=url)
        if ca_cert:
            self.configuration.ssl_ca_cert = ca_cert
        if insecure:
            self.configuration.verify_ssl = False

        self._token_url = self.config.get("token_url")
        self._issuer = self.config.get("issuer")
        self._token = None
        self._token_expiry = None
        self._idp_http = None
        if self._token_url or self._issuer:
            if not self.user or not self.passwd:
                raise vimconn.VimConnException(
                    "token_url or issuer needs the VIM account user and password "
                    "as the OAuth 2.0 client ID and secret"
                )
            self._idp_http = urllib3.PoolManager(
                cert_reqs="CERT_NONE" if insecure else "CERT_REQUIRED",
                ca_certs=ca_cert,
            )

    def check_vim_connectivity(self):
        self.logger.debug("Check VIM connectivity")
        with self._api_client() as api_client:
            try:
                FlavourServiceApi(api_client).list_flavours()
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
        if not ip_profile:
            ip_profile = {}
        if not ip_profile.get("subnet_address"):
            # Fake subnet is required
            subnet_rand = random.SystemRandom().randint(0, 255)
            ip_profile["subnet_address"] = "192.168.{}.0/24".format(subnet_rand)
        if "ip_version" not in ip_profile:
            ip_profile["ip_version"] = "IPv4"

        subnet = SubnetData(
            ipVersion=(
                IpVersion.IP_VERSION_IPV6
                if ip_profile["ip_version"] == "IPv6"
                else IpVersion.IP_VERSION_IPV4
            ),
            cidr=ip_profile["subnet_address"],
        )
        if ip_profile.get("gateway_address"):
            subnet.gateway_ip = ip_profile["gateway_address"]
        if "dhcp_enabled" in ip_profile:
            subnet.is_dhcp_enabled = not (
                ip_profile["dhcp_enabled"] == "false"
                or ip_profile["dhcp_enabled"] is False
            )
        else:
            subnet.is_dhcp_enabled = True

        net = Network(networkName=net_name, networkType=NetworkType.NETWORK_TYPE_GENEVE)
        if net_type in ["data", "ptp"] or provider_network_profile:
            if provider_network_profile is None:
                raise vimconn.VimConnNotSupportedException(
                    f"provider network should be defined for the {net_type} network type"
                )
            physical_network = provider_network_profile.get(
                "physical-network"
            ) or provider_network_profile.get("provider_network")
            if not physical_network:
                raise vimconn.VimConnNotSupportedException(
                    "provider network profile has no physical-network"
                )
            seg_id = provider_network_profile.get(
                "segmentation-id"
            ) or provider_network_profile.get("segmentation_id")
            net.provider_network, pool = split_physical_network(physical_network)
            if seg_id and str(seg_id) != "0":
                net.network_type = NetworkType.NETWORK_TYPE_VLAN
                net.segmentation_id = int(seg_id)
            else:
                net.network_type = NetworkType.NETWORK_TYPE_FLAT
            if pool:
                net.sriov = SriovSettings(pool=pool)
            if provider_network_profile.get("network-type") == "sriov":
                if not pool:
                    raise vimconn.VimConnNotSupportedException(
                        "network-type sriov needs physical-network <provider network>/<pool>"
                    )
            else:
                net.layer3_attributes = [subnet]
        else:
            net.layer3_attributes = [subnet]

        with self._api_client() as api_client:
            try:
                created = NetworkServiceApi(api_client).create_network(
                    CreateNetworkRequest(network=net)
                )
                if created is None or not created.network_id:
                    raise vimconn.VimConnUnexpectedResponse("received empty response")
                return created.network_id, {}
            except (ApiException, urllib3.exceptions.HTTPError) as ex:
                self._format_exception(ex)

    def get_network_list(self, filter_dict=None):
        self.logger.debug("Get Networks. Filter dict: %s", filter_dict)
        exprs = []
        for filter_name, filter_val in (filter_dict or {}).items():
            if filter_name == "name":
                exprs.append(f"(eq,networkName,{filter_value(filter_val)})")
            elif filter_name == "id":
                exprs.append(f"(eq,networkId,{filter_value(filter_val)})")
            elif filter_name == "shared":
                # Kube-VIM networks are never shared.
                if filter_val:
                    return []
            else:
                raise vimconn.VimConnNotSupportedException(
                    f"get network filter {filter_name} is not supported"
                )
        with self._api_client() as api_client:
            try:
                nets = NetworkServiceApi(api_client).list_networks(
                    filter=";".join(exprs) or None
                )
                return [network_from_kubevim(net) for net in nets or []]
            except (ApiException, urllib3.exceptions.HTTPError) as ex:
                self._format_exception(ex)

    def get_network(self, net_id):
        self.logger.debug("Network %s get request", net_id)
        with self._api_client() as api_client:
            try:
                net = NetworkServiceApi(api_client).get_network(net_id)
                if net is None:
                    raise vimconn.VimConnUnexpectedResponse("received empty response")
                return network_from_kubevim(net)
            except (ApiException, urllib3.exceptions.HTTPError) as ex:
                self._format_exception(ex)

    def delete_network(self, net_id, created_items=None):
        self.logger.debug("Network %s delete request", net_id)
        with self._api_client() as api_client:
            try:
                NetworkServiceApi(api_client).delete_network(net_id)
                return net_id
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
        with self._api_client() as api_client:
            try:
                flavor = FlavourServiceApi(api_client).get_flavour(flavor_id)
            except (ApiException, urllib3.exceptions.HTTPError) as e:
                self._format_exception(e)
        if flavor is None or not flavor.flavour_id:
            raise vimconn.VimConnUnexpectedResponse(
                "flavor id can't be empty in response"
            )
        boot_storage = [s for s in flavor.storage_attributes or [] if s.is_boot]
        if not boot_storage:
            raise vimconn.VimConnUnexpectedResponse(
                f"flavor missing boot storage: {flavor_id}"
            )
        # Same units new_flavor writes: ram in MB (M), disk in GiB (Gi)
        return {
            "id": flavor.flavour_id,
            "name": flavor.flavour_name,
            "ram": round(
                quantity_to_bytes(flavor.virtual_memory.virtual_mem_size) / 10**6
            ),
            "vcpus": flavor.virtual_cpu.num_virtual_cpu,
            "disk": round(quantity_to_bytes(boot_storage[0].size_of_storage) / 2**30),
        }

    def new_flavor(self, flavor_data):
        self.logger.debug("new flavour creation with data %s requested", flavor_data)
        flavor = Flavour(
            flavourName=flavor_data["name"],
            virtualMemory=VirtualMemoryData(virtualMemSize=f'{flavor_data["ram"]}M'),
            virtualCpu=VirtualCpuData(numVirtualCpu=flavor_data["vcpus"]),
            storageAttributes=[
                VirtualStorageData(
                    typeOfStorage=TypeOfStorage.TYPE_OF_STORAGE_VOLUME,
                    sizeOfStorage=f'{flavor_data["disk"]}Gi',
                    isBoot=True,
                )
            ],
        )
        with self._api_client() as api_client:
            try:
                created = FlavourServiceApi(api_client).create_flavour(
                    CreateFlavourRequest(flavour=flavor)
                )
                if created is None or not created.flavour_id:
                    raise vimconn.VimConnUnexpectedResponse(
                        "flavor_id in flavor creation response can't be empty"
                    )
                return created.flavour_id
            except (ApiException, urllib3.exceptions.HTTPError) as e:
                self._format_exception(e)

    def delete_flavor(self, flavor_id):
        self.logger.debug("Flavour %s delete request", flavor_id)
        with self._api_client() as api_client:
            try:
                FlavourServiceApi(api_client).delete_flavour(flavor_id)
                return flavor_id
            except (ApiException, urllib3.exceptions.HTTPError) as ex:
                self._format_exception(ex)

    def get_flavor_id_from_data(self, flavor_dict):
        query_filter = (
            f'(eq,virtualMemory/virtualMemSize,{flavor_dict["ram"]}M);'
            f'(eq,virtualCpu/numVirtualCpu,{flavor_dict["vcpus"]});'
            f'(eq,storageAttributes/sizeOfStorage,{flavor_dict["disk"]}Gi)'
        )
        with self._api_client() as api_client:
            try:
                flavors = FlavourServiceApi(api_client).list_flavours(
                    filter=query_filter
                )
            except (ApiException, urllib3.exceptions.HTTPError) as e:
                self._format_exception(e)
        if not flavors:
            raise vimconn.VimConnNotFoundException(
                "flavor with ram={}  cpu={} disk={} {} not found".format(
                    flavor_dict["ram"],
                    flavor_dict["vcpus"],
                    flavor_dict["disk"],
                    "and extended" if flavor_dict.get("extended") else "",
                )
            )
        if not flavors[0].flavour_id:
            raise vimconn.VimConnUnexpectedResponse(
                "flavor_id can't be empty in flavor query response"
            )
        return flavors[0].flavour_id

    def get_image_list(self, filter_dict={}):
        exprs = []
        for filter_name, filter_val in (filter_dict or {}).items():
            if filter_name == "id":
                exprs.append(f"(eq,imageId,{filter_value(filter_val)})")
            elif filter_name == "name":
                exprs.append(f"(eq,name,{filter_value(filter_val)})")
            elif filter_name == "location":
                exprs.append(f"(eq,source/http/url,{filter_value(filter_val)})")
            elif filter_name == "checksum":
                raise vimconn.VimConnNotImplemented(
                    "list images by the checksum is not supported yet"
                )
        img_filter = ";".join(exprs) or None
        self.logger.debug(
            "Image list request: %s. Filter query: %s", filter_dict, img_filter
        )
        with self._api_client() as api_client:
            try:
                images = ImageServiceApi(api_client).list_images(filter=img_filter)
            except (ApiException, urllib3.exceptions.HTTPError) as e:
                self._format_exception(e)
        resp = []
        for img in images or []:
            img_dict = convert_enums(img.model_dump(by_alias=True, exclude_none=True))
            if img.source:
                img_dict["source"] = img.source.to_dict()
            img_dict["id"] = img.image_id
            img_dict["name"] = img.name
            img_dict["checksum"] = "none"
            source = img.source.actual_instance if img.source else None
            if isinstance(source, ImageSourceHttp):
                img_dict["location"] = source.http.url
            else:
                img_dict["location"] = "None"
            resp.append(img_dict)
        return resp

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
        interfaces = []
        for idx, net in enumerate(net_list):
            if net["type"] == "virtual":
                nic_type = TypeVirtualNic.TYPE_VIRTUAL_NIC_BRIDGE
            elif net["type"] in ("PCI-PASSTHROUGH", "PCI_PASSTHROUGH", "PF"):
                raise vimconn.VimConnNotSupportedException(
                    f'PCI passthrough interface ({net["type"]}) is not supported by Kube-VIM'
                )
            elif net["type"] in ("SR-IOV", "VF", "VFnotShared"):
                nic_type = TypeVirtualNic.TYPE_VIRTUAL_NIC_SRIOV
            else:
                raise vimconn.VimConnNotSupportedException(
                    f'unknown network type: {net["type"]}'
                )
            if not net.get("net_id"):
                raise vimconn.VimConnNotSupportedException(
                    "an interface without a network is not supported by Kube-VIM"
                )
            # The interface name is its VIM id: unique in the VM, and returned by Kube-VIM.
            iface = NetworkInterfaceData(
                name=f"nic{idx}", networkId=net["net_id"], typeVirtualNic=nic_type
            )
            if nic_type == TypeVirtualNic.TYPE_VIRTUAL_NIC_SRIOV:
                # Kube-VIM assigns no addresses to SR-IOV interfaces; the guest does.
                iface.ip_assignment = IpAssignment.IP_ASSIGNMENT_NONE
            elif net.get("ip_address"):
                iface.ip_assignment = IpAssignment.IP_ASSIGNMENT_STATIC
                iface.ip_addresses = [net["ip_address"]]
            if net.get("mac_address"):
                iface.mac_address = net["mac_address"]
            interfaces.append(iface)

        req = CreateComputeRequest(
            compute=Compute(computeName=name, flavourId=flavor_id, imageId=image_id),
            networkInterfaces=interfaces,
        )
        if start is False:
            req.start = False
        _, userdata = self._create_user_data(cloud_config)
        if userdata:
            req.user_data = UserData(
                content=str(userdata),
                method=UserDataTransportationMethod.USER_DATA_TRANSPORTATION_METHOD_NO_CLOUD,
            )
        with self._api_client() as api_client:
            try:
                vm = ComputeServiceApi(api_client).create_compute(req)
            except (ApiException, urllib3.exceptions.HTTPError) as ex:
                self._format_exception(ex)
        created = {iface.name for iface in vm.network_interfaces or []}
        for net, iface in zip(net_list, interfaces):
            if iface.name in created:
                net["vim_id"] = iface.name
        return vm.compute_id, {}

    def get_vminstance(self, vm_id):
        self.logger.debug("Compute %s get request", vm_id)
        with self._api_client() as api_client:
            try:
                vm = ComputeServiceApi(api_client).get_compute(vm_id)
                return convert_enums(vm.model_dump(by_alias=True, exclude_none=True))
            except (ApiException, urllib3.exceptions.HTTPError) as ex:
                self._format_exception(ex)

    def delete_vminstance(self, vm_id, created_items=None, volumes_to_hold=None):
        self.logger.debug("Compute %s delete request", vm_id)
        with self._api_client() as api_client:
            try:
                ComputeServiceApi(api_client).delete_compute(vm_id)
                return vm_id
            except (ApiException, urllib3.exceptions.HTTPError) as ex:
                self._format_exception(ex)

    def refresh_vms_status(self, vm_list: List):
        res = dict()
        status_map = {
            ComputeRunningState.COMPUTE_RUNNING_STATE_STARTED.value: "ACTIVE",
            ComputeRunningState.COMPUTE_RUNNING_STATE_MIGRATING.value: "ACTIVE",
            ComputeRunningState.COMPUTE_RUNNING_STATE_PAUSED.value: "PAUSED",
            ComputeRunningState.COMPUTE_RUNNING_STATE_STARTING.value: "BUILD",
            ComputeRunningState.COMPUTE_RUNNING_STATE_STOPPING.value: "INACTIVE",
            ComputeRunningState.COMPUTE_RUNNING_STATE_STOPPED.value: "INACTIVE",
            ComputeRunningState.COMPUTE_RUNNING_STATE_TERMINATING.value: "INACTIVE",
        }
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
            running_state = vm_info.get("runningState")
            if running_state == ComputeRunningState.COMPUTE_RUNNING_STATE_FAILED.value:
                res[vm_id] = {
                    "status": "ERROR",
                    "error_msg": vm_info.get("statusDetail") or "unknown",
                }
                continue
            err_msg = ""
            vm_status = status_map.get(running_state, "OTHER")
            if vm_status == "OTHER":
                err_msg = f"status is {running_state}"

            interfaces = []
            for iface in vm_info.get("networkInterfaces") or []:
                if (
                    iface.get("operationalState")
                    != OperationalState.OPERATIONAL_STATE_ENABLED.value
                ):
                    # Need to think if Active:NoMgmtIp is better suited here
                    vm_status = "BUILD"
                ips = iface.get("ipAddresses") or []
                iface_dict = {
                    "vim_info": yaml.safe_dump(iface),
                    "mac_address": iface.get("macAddress"),
                    "ip_address": ips[0] if ips else None,
                    "vim_interface_id": iface.get("name"),
                    "compute_node": vm_info.get("hostId"),
                }
                if iface.get("networkId"):
                    iface_dict["vim_net_id"] = iface["networkId"]
                elif iface.get("isManagement"):
                    iface_dict["vim_net_id"] = "management"
                if iface.get("hostPciAddress"):
                    iface_dict["pci"] = iface["hostPciAddress"]
                interfaces.append(iface_dict)

            res[vm_id] = {
                "status": vm_status,
                "error_msg": err_msg,
                "vim_info": yaml.safe_dump(vm_info),
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

    def _api_client(self):
        if self._idp_http is None:
            return ApiClient(self.configuration)
        return _AuthApiClient(self.configuration, self)

    def _access_token(self):
        """Returns a cached client-credentials access token, fetching one when due."""
        if self._token and (
            self._token_expiry is None or time.monotonic() < self._token_expiry
        ):
            return self._token
        if not self._token_url:
            self._token_url = self._discover_token_url()
        fields = {"grant_type": "client_credentials"}
        if self.config.get("scope"):
            fields["scope"] = self.config["scope"]
        # RFC 6749 section 2.3.1: client ID and secret are form-encoded before Basic
        credentials = f"{quote_plus(self.user)}:{quote_plus(self.passwd)}".encode()
        body = self._idp_request(
            "POST",
            self._token_url,
            fields=fields,
            encode_multipart=False,
            headers={
                "Authorization": "Basic " + base64.b64encode(credentials).decode()
            },
        )
        if not isinstance(body, dict) or not body.get("access_token"):
            raise vimconn.VimConnUnexpectedResponse(
                f"token response from {self._token_url} has no access_token"
            )
        self._token = body["access_token"]
        expires_in = body.get("expires_in")
        self._token_expiry = (
            time.monotonic() + expires_in - TOKEN_REFRESH_MARGIN
            if expires_in is not None
            else None
        )
        self.logger.debug(
            "Fetched access token for client %s, expires in %ss", self.user, expires_in
        )
        return self._token

    def _discover_token_url(self):
        url = self._issuer.rstrip("/") + "/.well-known/openid-configuration"
        body = self._idp_request("GET", url)
        token_url = body.get("token_endpoint") if isinstance(body, dict) else None
        if not token_url:
            raise vimconn.VimConnUnexpectedResponse(f"no token_endpoint in {url}")
        return token_url

    def _idp_request(self, method, url, **kwargs):
        """Calls the IdP and returns the decoded JSON body."""
        try:
            response = self._idp_http.request(method, url, **kwargs)
        except urllib3.exceptions.HTTPError as ex:
            raise vimconn.VimConnConnectionException(f"cannot reach {url}: {ex}")
        try:
            body = json.loads(response.data)
        except ValueError:
            body = None
        if response.status in (400, 401):
            error = body.get("error") if isinstance(body, dict) else None
            raise vimconn.VimConnAuthException(
                f"{url} rejected client {self.user}: {response.status} {error or ''}"
            )
        if response.status != 200:
            raise vimconn.VimConnConnectionException(
                f"{url} returned {response.status}"
            )
        if body is None:
            raise vimconn.VimConnUnexpectedResponse(f"{url} returned invalid JSON")
        return body

    def _format_exception(self, exception):
        """Raises the vimconn exception for a failed Kube-VIM request."""
        if not isinstance(exception, ApiException):
            raise vimconn.VimConnConnectionException(exception)
        problem = {}
        try:
            problem = json.loads(exception.body or "{}")
        except ValueError:
            pass
        if not isinstance(problem, dict):
            problem = {}
        message = f"{exception.status} {problem.get('detail') or exception.reason}"
        if isinstance(exception, (UnauthorizedException, ForbiddenException)):
            raise vimconn.VimConnAuthException(message)
        elif isinstance(exception, NotFoundException):
            raise vimconn.VimConnNotFoundException(message)
        elif isinstance(exception, ConflictException):
            raise vimconn.VimConnConflictException(message)
        elif (
            exception.status == 501 or problem.get("type") == UNSUPPORTED_FIELD_PROBLEM
        ):
            raise vimconn.VimConnNotSupportedException(message)
        elif exception.status in (400, 422):
            raise vimconn.VimConnException(message)
        else:
            raise vimconn.VimConnConnectionException(message)
