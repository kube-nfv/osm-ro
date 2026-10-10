#!/usr/bin/env python3
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
##
"""Unit tests for the Kube-VIM VIM connector.

The HTTP layer of the generated kubevim-vivnfm-client is mocked, so every test runs
the real client: URL and query building, request serialization, status-to-exception
mapping and response deserialization. Responses use Kube-VIM's wire format and are
checked against the client models, which are generated from the kube-vim-api schema.
"""

import json
import logging
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from kubevim_vivnfm_client.models.pb_allocate_compute_response import (
    PbAllocateComputeResponse,
)
from kubevim_vivnfm_client.models.pb_allocate_network_response import (
    PbAllocateNetworkResponse,
)
from kubevim_vivnfm_client.models.pb_create_compute_flavour_response import (
    PbCreateComputeFlavourResponse,
)
from kubevim_vivnfm_client.models.pb_query_compute_flavour_response import (
    PbQueryComputeFlavourResponse,
)
from kubevim_vivnfm_client.models.pb_query_compute_response import (
    PbQueryComputeResponse,
)
from kubevim_vivnfm_client.models.pb_query_images_response import (
    PbQueryImagesResponse,
)
from kubevim_vivnfm_client.models.pb_query_network_response import (
    PbQueryNetworkResponse,
)
from kubevim_vivnfm_client.models.pb_terminate_compute_response import (
    PbTerminateComputeResponse,
)
from kubevim_vivnfm_client.models.pb_terminate_network_response import (
    PbTerminateNetworkResponse,
)
from kubevim_vivnfm_client.rest import RESTClientObject, RESTResponse
from osm_ro_plugin import vimconn
from osm_rovim_kubevim.vimconn_kubevim import quantity_to_bytes, vimconnector
import urllib3
import yaml

URL = "http://kubevim.test:8080"
MGMT_KEY = "network.vm.kubevirt.io/management"
READY_KEY = "interface.vm.kubevirt.io/ready"
FLAVOUR_NAME_KEY = "flavour.kubevim.kubenfv.io/attached-name"


def _assert_known_keys(body, parsed, path="$"):
    """Fails if body has a key the kube-vim-api model dropped while parsing."""
    if isinstance(body, dict):
        for key, value in body.items():
            if value is None:
                continue
            if key not in parsed:
                raise AssertionError(f"{path}.{key} is not in the kube-vim-api model")
            _assert_known_keys(value, parsed[key], f"{path}.{key}")
    elif isinstance(body, list):
        for i, (item, parsed_item) in enumerate(zip(body, parsed)):
            _assert_known_keys(item, parsed_item, f"{path}[{i}]")


def _http(status, body):
    return RESTResponse(
        urllib3.HTTPResponse(
            body=json.dumps(body).encode(),
            status=status,
            headers={"Content-Type": "application/json"},
            preload_content=True,
        )
    )


def ok(model, body):
    """A 200 response whose body is validated against the response model."""
    _assert_known_keys(body, model.from_dict(body).to_dict())
    return _http(200, body)


def error(status, message="error"):
    return _http(status, {"code": 2, "message": message})


def identifier(value):
    return {"value": value}


def network(net_id, name, net_type="NETWORK_TYPE_OVERLAY", segmentation_id=None):
    net = {
        "networkResourceId": identifier(net_id),
        "networkResourceName": name,
        "subnetId": [],
        "networkPort": [],
        "bandwidth": 100,
        "networkType": net_type,
        "networkQoS": [],
        "isShared": False,
        "operationalState": "ENABLED",
        "connectedNetworks": [],
    }
    if segmentation_id is not None:
        net["segmentationId"] = segmentation_id
    return net


def flavour(flavour_id, name="small", memory="2048M", cpus=2, disk="10Gi"):
    return {
        "flavourId": identifier(flavour_id),
        "isPublic": False,
        "virtualMemory": {"virtualMemSize": {"string": memory}},
        "virtualCpu": {"numVirtualCpu": cpus},
        "storageAttributes": [
            {
                "typeOfStorage": "volume",
                "sizeOfStorage": {"string": disk},
                "isBoot": True,
            }
        ],
        "virtualNetworkInterface": [],
        "metadata": {"fields": {FLAVOUR_NAME_KEY: name}},
    }


def image(image_id, name, location=None):
    fields = {"image.kubevim.kubenfv.io/source-url": location} if location else {}
    return {
        "softwareImageId": identifier(image_id),
        "name": name,
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-01T00:00:00Z",
        "size": {"string": "1Gi"},
        "status": "AVAILABLE",
        "metadata": {"fields": fields},
    }


def nic(resource_id, net_id=None, mgmt=False, ready=True, ip=None, mac=None):
    return {
        "resourceId": identifier(resource_id),
        "ownerId": identifier("vm-1"),
        "networkId": identifier(net_id) if net_id else None,
        "ipAddress": [{"ip": ip}] if ip else [],
        "typeVirtualNic": "TYPE_VIRTUAL_NIC_BRIDGE",
        "macAddress": {"mac": mac or "initializing"},
        "bandwidth": 0,
        "operationalState": "ENABLED",
        "metadata": {
            "fields": {
                MGMT_KEY: "true" if mgmt else "false",
                READY_KEY: "true" if ready else "false",
            }
        },
    }


def compute(vm_id="vm-1", state="RUNNING", nics=(), reason=None):
    fields = {"status.vmi.kubevirt.io/phase": "Running"}
    if reason:
        fields["status.vmi.kubevirt.io/reason"] = reason
    return {
        "computeId": identifier(vm_id),
        "computeName": "vm",
        "flavourId": identifier("flavour-1"),
        "virtualCpu": {},
        "virtualMemory": {},
        "virtualNetworkInterface": list(nics),
        "virtualDisks": [],
        "vcImageId": identifier("image-1"),
        "hostId": identifier("node-1"),
        "operationalState": "ENABLED",
        "runningState": state,
        "metadata": {"fields": fields},
    }


def networks(*nets):
    return ok(PbQueryNetworkResponse, {"queryNetworkResult": list(nets)})


def flavours(*items):
    return ok(PbQueryComputeFlavourResponse, {"flavours": list(items)})


def computes(*items):
    return ok(PbQueryComputeResponse, {"queryResult": list(items)})


class KubevimTestCase(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(RESTClientObject, "request", autospec=True)
        self.request = patcher.start()
        self.addCleanup(patcher.stop)
        self.conn = vimconnector(
            uuid="vim-uuid",
            name="kubevim",
            tenant_id=None,
            tenant_name=None,
            url=URL,
        )

    def respond(self, *responses):
        self.request.side_effect = list(responses)

    def sent(self, index=-1):
        """Returns (method, path, query, body) of a request the client sent."""
        call = self.request.call_args_list[index]
        url = urlsplit(call.args[2])
        query = {
            k: v[0] for k, v in parse_qs(url.query, keep_blank_values=True).items()
        }
        return call.args[1], url.path, query, call.kwargs.get("body")


class TestQuantity(unittest.TestCase):
    def test_suffixes(self):
        cases = {
            "1024M": 1024 * 10**6,
            "2G": 2 * 10**9,
            "1k": 10**3,
            "10Gi": 10 * 2**30,
            "1Ti": 2**40,
            "512Mi": 512 * 2**20,
            "100": 100,
            "1e3": 1000,
        }
        for quantity, expected in cases.items():
            with self.subTest(quantity=quantity):
                self.assertEqual(quantity_to_bytes(quantity), expected)

    def test_invalid(self):
        for quantity in ("", "Gi", "10Xi", "ten"):
            with self.subTest(quantity=quantity):
                with self.assertRaises(vimconn.VimConnUnexpectedResponse):
                    quantity_to_bytes(quantity)


class TestErrorMapping(KubevimTestCase):
    def test_connectivity_ok(self):
        self.respond(flavours())
        self.assertIsNone(self.conn.check_vim_connectivity())
        self.assertEqual(self.sent(), ("GET", "/vivnfm/v5/flavours", {}, None))

    def test_http_errors(self):
        cases = {
            400: vimconn.VimConnException,
            401: vimconn.VimConnAuthException,
            404: vimconn.VimConnNotFoundException,
            409: vimconn.VimConnConflictException,
            500: vimconn.VimConnConnectionException,
            503: vimconn.VimConnConnectionException,
        }
        for status, exception in cases.items():
            with self.subTest(status=status):
                self.respond(error(status))
                with self.assertRaises(exception) as ctx:
                    self.conn.check_vim_connectivity()
                self.assertIs(type(ctx.exception), exception)

    def test_gateway_unreachable(self):
        self.request.side_effect = urllib3.exceptions.MaxRetryError(None, URL)
        with self.assertRaises(vimconn.VimConnConnectionException):
            self.conn.check_vim_connectivity()

    def test_log_level(self):
        conn = vimconnector("vim-uuid", "kubevim", None, None, URL, log_level="DEBUG")
        self.assertEqual(conn.logger.level, logging.DEBUG)


class TestNewNetwork(KubevimTestCase):
    def allocate(self, *args, **kwargs):
        self.respond(
            ok(PbAllocateNetworkResponse, {"networkData": network("net-1", "n")})
        )
        result = self.conn.new_network(*args, **kwargs)
        method, path, _, body = self.sent()
        self.assertEqual((method, path), ("POST", "/vivnfm/v5/networks"))
        self.assertEqual(result, ("net-1", {}))
        return body

    def test_overlay(self):
        body = self.allocate(
            "net-a",
            "bridge",
            ip_profile={
                "ip_version": "IPv4",
                "subnet_address": "10.0.0.0/24",
                "gateway_address": "10.0.0.1",
                "dhcp_enabled": False,
            },
            shared=True,
        )
        self.assertEqual(body["networkResourceType"], "NETWORK")
        self.assertEqual(body["networkResourceName"], "net-a")
        net = body["typeNetworkData"]
        self.assertEqual(net["networkType"], "NETWORK_TYPE_OVERLAY")
        self.assertTrue(net["isShared"])
        self.assertEqual(
            net["layer3Attributes"],
            [
                {
                    "ipVersion": "IPV4",
                    "gatewayIp": {"ip": "10.0.0.1"},
                    "cidr": {"cidr": "10.0.0.0/24"},
                    "isDhcpEnabled": False,
                }
            ],
        )
        self.assertNotIn("segmentationId", net)

    def test_ipv6_and_dhcp_default(self):
        body = self.allocate(
            "net-a",
            "bridge",
            ip_profile={"ip_version": "IPv6", "subnet_address": "fd00::/64"},
        )
        subnet = body["typeNetworkData"]["layer3Attributes"][0]
        self.assertEqual(subnet["ipVersion"], "IPV6")
        self.assertTrue(subnet["isDhcpEnabled"])

    def test_dhcp_disabled_as_string(self):
        body = self.allocate(
            "net-a",
            "bridge",
            ip_profile={"subnet_address": "10.0.0.0/24", "dhcp_enabled": "false"},
        )
        self.assertFalse(
            body["typeNetworkData"]["layer3Attributes"][0]["isDhcpEnabled"]
        )

    def test_random_subnet_without_ip_profile(self):
        with patch("osm_rovim_kubevim.vimconn_kubevim.random.SystemRandom") as rnd:
            rnd.return_value.randint.return_value = 42
            body = self.allocate("net-a", "bridge")
        subnet = body["typeNetworkData"]["layer3Attributes"][0]
        self.assertEqual(subnet["cidr"], {"cidr": "192.168.42.0/24"})
        self.assertEqual(subnet["ipVersion"], "IPV4")
        rnd.return_value.randint.assert_called_once_with(0, 255)

    def test_underlay_vlan(self):
        body = self.allocate(
            "net-a",
            "data",
            ip_profile={"subnet_address": "10.0.0.0/24"},
            provider_network_profile={
                "physical-network": "physnet1",
                "segmentation-id": 100,
            },
        )
        net = body["typeNetworkData"]
        self.assertEqual(net["networkType"], "NETWORK_TYPE_UNDERLAY")
        self.assertEqual(net["providerNetwork"], "physnet1")
        self.assertEqual(net["segmentationId"], "100")
        self.assertEqual(len(net["layer3Attributes"]), 1)

    def test_underlay_flat_alternative_keys(self):
        body = self.allocate(
            "net-a",
            "ptp",
            provider_network_profile={
                "provider_network": "physnet2",
                "segmentation_id": 0,
            },
        )
        net = body["typeNetworkData"]
        self.assertEqual(net["providerNetwork"], "physnet2")
        self.assertNotIn("segmentationId", net)

    def test_sriov(self):
        body = self.allocate(
            "net-a",
            "data",
            provider_network_profile={
                "network-type": "sriov",
                "physical-network": "sriov-pool",
                "segmentation-id": 200,
            },
        )
        net = body["typeNetworkData"]
        self.assertEqual(net["networkType"], "NETWORK_TYPE_SRIOV")
        self.assertEqual(net["providerNetwork"], "sriov-pool")
        self.assertEqual(net["segmentationId"], "200")
        self.assertNotIn("layer3Attributes", net)

    def test_data_network_without_provider_profile(self):
        with self.assertRaises(vimconn.VimConnNotSupportedException):
            self.conn.new_network("net-a", "data")
        self.request.assert_not_called()

    def test_empty_response(self):
        self.respond(ok(PbAllocateNetworkResponse, {}))
        with self.assertRaises(vimconn.VimConnUnexpectedResponse):
            self.conn.new_network("net-a", "bridge")

    def test_api_error(self):
        self.respond(error(409))
        with self.assertRaises(vimconn.VimConnConflictException):
            self.conn.new_network("net-a", "bridge")


class TestNetworkQueries(KubevimTestCase):
    def test_list_without_filter(self):
        self.respond(networks(network("net-1", "a"), network("net-2", "b")))
        result = self.conn.get_network_list()
        self.assertEqual([n["id"] for n in result], ["net-1", "net-2"])
        self.assertEqual(
            self.sent(),
            (
                "GET",
                "/vivnfm/v5/networks",
                {"networkResourceType": "NETWORK", "queryNetworkFilter.value": ""},
                None,
            ),
        )

    def test_list_filters(self):
        self.respond(networks())
        self.assertEqual(
            self.conn.get_network_list({"name": "a", "id": "net-1", "shared": True}), []
        )
        self.assertEqual(
            self.sent()[2]["queryNetworkFilter.value"],
            "filter=(eq,networkResourceName,a);(eq,networkResourceId/value,net-1);"
            "(eq,isShared,true)",
        )

    def test_list_empty_result(self):
        self.respond(ok(PbQueryNetworkResponse, {}))
        self.assertEqual(self.conn.get_network_list(), [])

    def test_list_unsupported_filter(self):
        with self.assertRaises(vimconn.VimConnNotSupportedException):
            self.conn.get_network_list({"tenant_id": "x"})
        self.request.assert_not_called()

    def test_network_types(self):
        cases = [
            (network("n", "a"), "vxlan", 0),
            (network("n", "a", "NETWORK_TYPE_UNDERLAY", "100"), "vlan", 100),
            (network("n", "a", "NETWORK_TYPE_UNDERLAY", "0"), "flat", None),
            (network("n", "a", "NETWORK_TYPE_UNDERLAY"), "flat", None),
            (network("n", "a", "NETWORK_TYPE_SRIOV", "200"), "SR-IOV", 200),
            (network("n", "a", "NETWORK_TYPE_SRIOV"), "SR-IOV", None),
        ]
        for net, net_type, segmentation_id in cases:
            with self.subTest(net_type=net_type, segmentation_id=segmentation_id):
                self.respond(networks(net))
                result = self.conn.get_network("n")
                self.assertEqual(result["network_type"], net_type)
                self.assertEqual(result.get("segmentation_id"), segmentation_id)

    def test_get_network(self):
        net = network("net-1", "a", "NETWORK_TYPE_UNDERLAY", "100")
        net["providerNetwork"] = "physnet1"
        self.respond(networks(net))
        result = self.conn.get_network("net-1")
        self.assertEqual(result["id"], "net-1")
        self.assertEqual(result["name"], "a")
        self.assertEqual(result["status"], "ACTIVE")
        self.assertFalse(result["shared"])
        self.assertEqual(result["providerNetwork"], "physnet1")
        for key in ("networkResourceId", "networkType", "connectedNetworks"):
            self.assertNotIn(key, result)
        self.assertEqual(
            self.sent()[2]["queryNetworkFilter.value"],
            "filter=(eq,networkResourceId/value,net-1)",
        )

    def test_get_network_disabled(self):
        net = network("net-1", "a")
        net["operationalState"] = "DISABLED"
        self.respond(networks(net))
        self.assertEqual(self.conn.get_network("net-1")["status"], "INACTIVE")

    def test_get_network_not_found(self):
        self.respond(networks())
        with self.assertRaises(vimconn.VimConnNotFoundException):
            self.conn.get_network("net-1")

    def test_get_network_ambiguous(self):
        self.respond(networks(network("net-1", "a"), network("net-1", "b")))
        with self.assertRaises(vimconn.VimConnUnexpectedResponse):
            self.conn.get_network("net-1")

    def test_get_network_api_error(self):
        self.respond(error(500))
        with self.assertRaises(vimconn.VimConnConnectionException):
            self.conn.get_network("net-1")

    def test_delete_network(self):
        self.respond(
            ok(PbTerminateNetworkResponse, {"networkResourceId": identifier("net-1")})
        )
        self.assertEqual(self.conn.delete_network("net-1"), "net-1")
        self.assertEqual(self.sent()[:2], ("DELETE", "/vivnfm/v5/networks/net-1"))

    def test_delete_network_not_found(self):
        self.respond(error(404))
        with self.assertRaises(vimconn.VimConnNotFoundException):
            self.conn.delete_network("net-1")

    def test_refresh_nets_status(self):
        self.respond(networks(network("net-1", "a")))
        result = self.conn.refresh_nets_status(["net-1", "net-gone"])
        self.assertEqual(result["net-1"]["status"], "ACTIVE")
        self.assertEqual(yaml.safe_load(result["net-1"]["vim_info"])["id"], "net-1")
        self.assertEqual(result["net-gone"], {"status": "DELETED"})

    def test_refresh_nets_status_unreachable(self):
        self.request.side_effect = urllib3.exceptions.MaxRetryError(None, URL)
        result = self.conn.refresh_nets_status(["net-1", "net-2"])
        for net_id in ("net-1", "net-2"):
            self.assertEqual(result[net_id]["status"], "VIM_ERROR")
            self.assertIn("Max retries", result[net_id]["error_msg"])


class TestFlavors(KubevimTestCase):
    def test_get_flavor(self):
        self.respond(flavours(flavour("flavour-1")))
        self.assertEqual(
            self.conn.get_flavor("flavour-1"),
            {"id": "flavour-1", "name": "small", "ram": 2048, "vcpus": 2, "disk": 10},
        )
        self.assertEqual(
            self.sent(),
            (
                "GET",
                "/vivnfm/v5/flavours",
                {
                    "queryComputeFlavourFilter.value": "filter=(eq,flavourId/value,flavour-1)"
                },
                None,
            ),
        )

    def test_get_flavor_canonical_quantities(self):
        # Kubernetes returns quantities in canonical form, e.g. 2000M as 2G
        cases = [("2G", "20Gi", 2000, 20), ("4096M", "1Ti", 4096, 1024)]
        for memory, disk, ram, disk_gb in cases:
            with self.subTest(memory=memory, disk=disk):
                self.respond(flavours(flavour("f", memory=memory, disk=disk)))
                result = self.conn.get_flavor(flavor_id="f")
                self.assertEqual((result["ram"], result["disk"]), (ram, disk_gb))

    def test_get_flavor_by_name_not_supported(self):
        with self.assertRaises(vimconn.VimConnNotSupportedException):
            self.conn.get_flavor(flavor_name="small")
        self.request.assert_not_called()

    def test_get_flavor_not_found(self):
        self.respond(flavours())
        with self.assertRaises(vimconn.VimConnNotFoundException):
            self.conn.get_flavor("flavour-1")

    def test_get_flavor_api_error(self):
        self.respond(error(500))
        with self.assertRaises(vimconn.VimConnConnectionException):
            self.conn.get_flavor("flavour-1")

    def test_get_flavor_unexpected_responses(self):
        no_name = flavour("f")
        no_name["metadata"] = {"fields": {}}
        no_boot = flavour("f")
        no_boot["storageAttributes"][0]["isBoot"] = False
        no_id = flavour("f")
        del no_id["flavourId"]
        cases = {
            "ambiguous": flavours(flavour("f"), flavour("f")),
            "no name": flavours(no_name),
            "no boot storage": flavours(no_boot),
            "no id": flavours(no_id),
        }
        for case, response in cases.items():
            with self.subTest(case=case):
                self.respond(response)
                with self.assertRaises(vimconn.VimConnUnexpectedResponse):
                    self.conn.get_flavor("f")

    def test_new_flavor(self):
        self.respond(
            ok(PbCreateComputeFlavourResponse, {"flavourId": identifier("flavour-1")})
        )
        result = self.conn.new_flavor(
            {"name": "small", "ram": 2048, "vcpus": 2, "disk": 10}
        )
        self.assertEqual(result, "flavour-1")
        method, path, _, body = self.sent()
        self.assertEqual((method, path), ("POST", "/vivnfm/v5/flavours"))
        self.assertEqual(
            body,
            {
                "flavour": {
                    "isPublic": True,
                    "virtualMemory": {"virtualMemSize": {"string": "2048M"}},
                    "virtualCpu": {"numVirtualCpu": 2},
                    "storageAttributes": [
                        {
                            "typeOfStorage": "volume",
                            "sizeOfStorage": {"string": "10Gi"},
                            "isBoot": True,
                        }
                    ],
                },
                "metaData": {"fields": {FLAVOUR_NAME_KEY: "small"}},
            },
        )

    def test_new_flavor_api_error(self):
        self.respond(error(409))
        with self.assertRaises(vimconn.VimConnConflictException):
            self.conn.new_flavor({"name": "small", "ram": 2048, "vcpus": 2, "disk": 10})

    def test_delete_flavor(self):
        self.respond(_http(200, {}))
        self.assertEqual(self.conn.delete_flavor("flavour-1"), "flavour-1")
        self.assertEqual(self.sent()[:2], ("DELETE", "/vivnfm/v5/flavours/flavour-1"))

    def test_delete_flavor_not_found(self):
        self.respond(error(404))
        with self.assertRaises(vimconn.VimConnNotFoundException):
            self.conn.delete_flavor("flavour-1")

    def test_get_flavor_id_from_data(self):
        self.respond(flavours(flavour("flavour-1"), flavour("flavour-2")))
        result = self.conn.get_flavor_id_from_data(
            {"ram": 2048, "vcpus": 2, "disk": 10}
        )
        self.assertEqual(result, "flavour-1")
        self.assertEqual(
            self.sent()[2]["queryComputeFlavourFilter.value"],
            "filter=(eq,virtualMemory/virtualMemSize,2048M);"
            "(eq,virtualCpu/numVirtualCpu,2);(eq,storageAttributes/sizeOfStorage,10Gi)",
        )

    def test_get_flavor_id_from_data_not_found(self):
        self.respond(flavours())
        with self.assertRaises(vimconn.VimConnNotFoundException):
            self.conn.get_flavor_id_from_data({"ram": 2048, "vcpus": 2, "disk": 10})

    def test_get_flavor_id_from_data_without_id(self):
        no_id = flavour("f")
        del no_id["flavourId"]
        self.respond(flavours(no_id))
        with self.assertRaises(vimconn.VimConnUnexpectedResponse):
            self.conn.get_flavor_id_from_data({"ram": 2048, "vcpus": 2, "disk": 10})

    def test_get_flavor_id_from_data_api_error(self):
        self.respond(error(500))
        with self.assertRaises(vimconn.VimConnConnectionException):
            self.conn.get_flavor_id_from_data({"ram": 2048, "vcpus": 2, "disk": 10})


class TestImages(KubevimTestCase):
    def test_list(self):
        self.respond(
            ok(
                PbQueryImagesResponse,
                {
                    "softwareImagesInformation": [
                        image(
                            "image-1", "cirros", location="https://example.com/c.img"
                        ),
                        image("image-2", "ubuntu"),
                    ]
                },
            )
        )
        result = self.conn.get_image_list()
        self.assertEqual([i["id"] for i in result], ["image-1", "image-2"])
        self.assertEqual(result[0]["name"], "cirros")
        self.assertEqual(result[0]["location"], "https://example.com/c.img")
        self.assertEqual(result[1]["location"], "None")
        self.assertEqual(
            self.sent(),
            ("GET", "/vivnfm/v5/images", {"imageQueryFilter.value": ""}, None),
        )

    def test_filters(self):
        cases = [
            ({"id": "image-1"}, "filter=(eq,softwareImageId/value,image-1)"),
            ({"name": "cirros"}, "filter=(eq,name,cirros)"),
            ({}, ""),
            (None, ""),
        ]
        for filter_dict, query in cases:
            with self.subTest(filter_dict=filter_dict):
                self.respond(ok(PbQueryImagesResponse, {}))
                self.assertEqual(self.conn.get_image_list(filter_dict), [])
                self.assertEqual(self.sent()[2]["imageQueryFilter.value"], query)

    def test_unsupported_filters(self):
        for key in ("location", "checksum"):
            with self.subTest(key=key):
                with self.assertRaises(vimconn.VimConnNotImplemented):
                    self.conn.get_image_list({key: "x"})
        self.request.assert_not_called()

    def test_api_error(self):
        self.respond(error(500))
        with self.assertRaises(vimconn.VimConnConnectionException):
            self.conn.get_image_list()


class TestNewVminstance(KubevimTestCase):
    def create(self, net_list, response_nics, **kwargs):
        self.respond(
            ok(
                PbAllocateComputeResponse,
                {"computeData": compute("vm-1", "STARTING", response_nics)},
            )
        )
        result = self.conn.new_vminstance(
            "vm", "description", True, "image-1", "flavour-1", [], net_list, **kwargs
        )
        method, path, _, body = self.sent()
        self.assertEqual((method, path), ("POST", "/vivnfm/v5/compute"))
        self.assertEqual(result, ("vm-1", {}))
        return body

    def test_interfaces(self):
        net_list = [
            {"name": "eth1", "type": "virtual", "net_id": "net-1"},
            {
                "name": "eth2",
                "type": "SR-IOV",
                "net_id": "net-2",
                "ip_address": "10.0.0.5",
                "mac_address": "52:54:00:00:00:02",
                "bw": 2,
            },
        ]
        body = self.create(
            net_list,
            [nic("default", mgmt=True), nic("nic-1", "net-1"), nic("nic-2", "net-2")],
        )
        self.assertEqual(body["computeName"], "vm")
        self.assertEqual(body["computeFlavourId"], identifier("flavour-1"))
        self.assertEqual(body["vcImageId"], identifier("image-1"))
        self.assertEqual(
            body["interfaceData"],
            [
                {
                    "networkId": identifier("net-1"),
                    "typeVirtualNic": "TYPE_VIRTUAL_NIC_BRIDGE",
                    "metadata": {
                        "fields": {
                            "compute.kubevim.kubenfv.io/network.subnet.assignment": "random"
                        }
                    },
                },
                {
                    "networkId": identifier("net-2"),
                    "typeVirtualNic": "TYPE_VIRTUAL_NIC_SRIOV",
                    "bandwidth": 2000,
                },
            ],
        )
        self.assertEqual(
            body["interfaceIPAM"],
            [
                {"networkId": identifier("net-1")},
                {
                    "networkId": identifier("net-2"),
                    "ipAddress": {"ip": "10.0.0.5"},
                    "macAddress": {"mac": "52:54:00:00:00:02"},
                },
            ],
        )
        self.assertNotIn("userData", body)
        self.assertEqual([n["vim_id"] for n in net_list], ["nic-1", "nic-2"])

    def test_vf_types(self):
        for nic_type in ("VF", "VFnotShared"):
            with self.subTest(nic_type=nic_type):
                body = self.create(
                    [{"type": nic_type, "net_id": "net-1"}], [nic("nic-1", "net-1")]
                )
                self.assertEqual(
                    body["interfaceData"][0]["typeVirtualNic"], "TYPE_VIRTUAL_NIC_SRIOV"
                )

    def test_user_data(self):
        body = self.create(
            [{"type": "virtual", "net_id": "net-1"}],
            [nic("nic-1", "net-1")],
            cloud_config={"key-pairs": ["ssh-rsa AAAA test"]},
        )
        self.assertEqual(body["userData"]["method"], "NO_CLOUD")
        self.assertIn("ssh-rsa AAAA test", body["userData"]["content"])

    def test_rejected_interfaces(self):
        cases = {
            "duplicate network": [
                {"type": "virtual", "net_id": "net-1"},
                {"type": "virtual", "net_id": "net-1"},
            ],
            "PF": [{"type": "PF", "net_id": "net-1"}],
            "PCI-PASSTHROUGH": [{"type": "PCI-PASSTHROUGH", "net_id": "net-1"}],
            "unknown type": [{"type": "bogus", "net_id": "net-1"}],
        }
        for case, net_list in cases.items():
            with self.subTest(case=case):
                with self.assertRaises(vimconn.VimConnNotSupportedException):
                    self.conn.new_vminstance(
                        "vm", "", True, "image-1", "flavour-1", [], net_list
                    )
        self.request.assert_not_called()

    def test_api_error(self):
        self.respond(error(404, "flavour not found"))
        with self.assertRaises(vimconn.VimConnNotFoundException):
            self.conn.new_vminstance(
                "vm",
                "",
                True,
                "image-1",
                "flavour-1",
                [],
                [{"type": "virtual", "net_id": "net-1"}],
            )


class TestVminstance(KubevimTestCase):
    def test_get_vminstance(self):
        self.respond(computes(compute("vm-1", nics=[nic("default", mgmt=True)])))
        result = self.conn.get_vminstance("vm-1")
        self.assertEqual(result["computeId"], identifier("vm-1"))
        self.assertEqual(result["runningState"], "RUNNING")
        self.assertEqual(
            self.sent(),
            (
                "GET",
                "/vivnfm/v5/compute",
                {"queryComputeFilter.value": "filter=(eq,computeId/value,vm-1)"},
                None,
            ),
        )

    def test_get_vminstance_not_found(self):
        self.respond(computes())
        with self.assertRaises(vimconn.VimConnNotFoundException):
            self.conn.get_vminstance("vm-1")

    def test_get_vminstance_ambiguous(self):
        self.respond(computes(compute("vm-1"), compute("vm-1")))
        with self.assertRaises(vimconn.VimConnUnexpectedResponse):
            self.conn.get_vminstance("vm-1")

    def test_delete_vminstance(self):
        self.respond(ok(PbTerminateComputeResponse, {"computeId": identifier("vm-1")}))
        self.assertEqual(self.conn.delete_vminstance("vm-1"), "vm-1")
        self.assertEqual(self.sent()[:2], ("DELETE", "/vivnfm/v5/compute/vm-1"))

    def test_delete_vminstance_id_mismatch(self):
        self.respond(ok(PbTerminateComputeResponse, {"computeId": identifier("vm-2")}))
        with self.assertRaises(vimconn.VimConnUnexpectedResponse):
            self.conn.delete_vminstance("vm-1")

    def test_delete_vminstance_not_found(self):
        self.respond(error(404))
        with self.assertRaises(vimconn.VimConnNotFoundException):
            self.conn.delete_vminstance("vm-1")

    def test_action_not_supported(self):
        with self.assertRaises(vimconn.VimConnNotSupportedException):
            self.conn.action_vminstance("vm-1", {"start": None})
        self.request.assert_not_called()


class TestRefreshVmsStatus(KubevimTestCase):
    def test_active(self):
        nics = [
            nic("default", mgmt=True, ip="10.244.0.7", mac="52:54:00:00:00:01"),
            nic("nic-1", "net-1", ip="192.168.1.10", mac="52:54:00:00:00:02"),
        ]
        self.respond(computes(compute("vm-1", "RUNNING", nics)))
        result = self.conn.refresh_vms_status(["vm-1"])["vm-1"]
        self.assertEqual(result["status"], "ACTIVE")
        self.assertEqual(result["error_msg"], "")
        self.assertEqual(
            yaml.safe_load(result["vim_info"])["computeId"], identifier("vm-1")
        )
        mgmt, data = result["interfaces"]
        self.assertEqual(mgmt["vim_net_id"], "management")
        self.assertEqual(mgmt["vim_interface_id"], "default")
        self.assertEqual(mgmt["ip_address"], "10.244.0.7")
        self.assertEqual(data["vim_net_id"], "net-1")
        self.assertEqual(data["vim_interface_id"], "nic-1")
        self.assertEqual(data["ip_address"], "192.168.1.10")
        self.assertEqual(data["mac_address"], "52:54:00:00:00:02")
        self.assertEqual(data["compute_node"], "node-1")

    def test_interface_without_ip(self):
        self.respond(computes(compute("vm-1", "RUNNING", [nic("nic-1", "net-1")])))
        result = self.conn.refresh_vms_status(["vm-1"])["vm-1"]
        self.assertIsNone(result["interfaces"][0]["ip_address"])

    def test_interface_not_ready_is_build(self):
        nics = [nic("default", mgmt=True), nic("nic-1", "net-1", ready=False)]
        self.respond(computes(compute("vm-1", "RUNNING", nics)))
        result = self.conn.refresh_vms_status(["vm-1"])["vm-1"]
        self.assertEqual(result["status"], "BUILD")
        self.assertEqual(
            [i["vim_interface_id"] for i in result["interfaces"]], ["default"]
        )

    def test_running_states(self):
        cases = {
            "STARTING": "BUILD",
            "PAUSED": "PAUSED",
            "SUSPENDED": "SUSPENDED",
            "STOPPED": "INACTIVE",
            "TERMINATING": "INACTIVE",
        }
        for state, status in cases.items():
            with self.subTest(state=state):
                self.respond(computes(compute("vm-1", state)))
                result = self.conn.refresh_vms_status(["vm-1"])["vm-1"]
                self.assertEqual(result["status"], status)
                self.assertEqual(result["error_msg"], "")

    def test_unknown_state(self):
        self.respond(computes(compute("vm-1", "UNKNOWN")))
        result = self.conn.refresh_vms_status(["vm-1"])["vm-1"]
        self.assertEqual(result["status"], "OTHER")
        self.assertEqual(result["error_msg"], "status is UNKNOWN")

    def test_failed(self):
        self.respond(computes(compute("vm-1", "FAILED", reason="Unschedulable")))
        result = self.conn.refresh_vms_status(["vm-1"])
        self.assertEqual(
            result["vm-1"], {"status": "ERROR", "error_msg": "Unschedulable"}
        )

    def test_failed_without_reason(self):
        self.respond(computes(compute("vm-1", "FAILED")))
        result = self.conn.refresh_vms_status(["vm-1"])
        self.assertEqual(result["vm-1"], {"status": "ERROR", "error_msg": "unknown"})

    def test_deleted(self):
        self.respond(computes())
        result = self.conn.refresh_vms_status(["vm-1"])
        self.assertEqual(result["vm-1"]["status"], "DELETED")

    def test_unreachable(self):
        self.request.side_effect = urllib3.exceptions.MaxRetryError(None, URL)
        result = self.conn.refresh_vms_status(["vm-1"])
        self.assertEqual(result["vm-1"]["status"], "VIM_ERROR")
        self.assertIn("Max retries", result["vm-1"]["error_msg"])

    def test_several_vms(self):
        self.respond(computes(compute("vm-1")), computes())
        result = self.conn.refresh_vms_status(["vm-1", "vm-2"])
        self.assertEqual(result["vm-1"]["status"], "ACTIVE")
        self.assertEqual(result["vm-2"]["status"], "DELETED")


class TestInjectUserKey(unittest.TestCase):
    def inject(self, config):
        conn = vimconnector("vim-uuid", "kubevim", None, None, URL, config=config)
        with patch.object(vimconn.VimConnector, "inject_user_key") as parent:
            conn.inject_user_key("10.0.0.5", "ubuntu", "ssh-rsa KEY", "ro-key")
        return parent.call_args.kwargs

    def test_uses_config_ssh_key(self):
        self.assertEqual(self.inject({"ssh_key": "vim-key"})["ro_key"], "vim-key")

    def test_keeps_ro_key_without_config(self):
        kwargs = self.inject({})
        self.assertEqual(
            kwargs,
            {
                "ip_addr": "10.0.0.5",
                "user": "ubuntu",
                "key": "ssh-rsa KEY",
                "ro_key": "ro-key",
                "password": None,
            },
        )


if __name__ == "__main__":
    unittest.main()
