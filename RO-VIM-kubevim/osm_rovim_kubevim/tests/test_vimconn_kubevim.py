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

The HTTP layer of the generated kubevim-client is mocked, so every test runs the real
client: URL and query building, request serialization, status-to-exception mapping and
response deserialization. Responses use Kube-VIM's wire format and are checked against
the client models, which are generated from the kube-vim-api schema.
"""

import base64
import io
import json
import logging
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from kubevim_client.models.compute import Compute
from kubevim_client.models.flavour import Flavour
from kubevim_client.models.image import Image
from kubevim_client.models.network import Network
from kubevim_client.rest import RESTClientObject, RESTResponse
from osm_ro_plugin import vimconn
from osm_rovim_kubevim.vimconn_kubevim import (
    quantity_to_bytes,
    split_physical_network,
    vimconnector,
)
import urllib3
import yaml

URL = "http://kubevim.test:8080"
NET_ID = "6f0d3c1e-8a52-4a8e-9a43-2f1d6b1c7e10"
NET_ID_2 = "7a1e4d2f-9b63-4b9f-8b54-3e2f7c2d8f21"
FLAVOUR_ID = "9a8b7c6d-5e4f-4a3b-9c2d-1e0f9a8b7c6d"
IMAGE_ID = "5f0c9d2e-3a4b-4c1d-9e8f-0a1b2c3d4e5f"
VM_ID = "d4e5f6a7-b8c9-4d0e-9f1a-2b3c4d5e6f7a"
PROBLEMS = "https://kubevim.kubenfv.io/problems/"


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


def _merge(a, b):
    """Merges dict b into dict a, recursively."""
    if not (isinstance(a, dict) and isinstance(b, dict)):
        return b
    return {k: _merge(a.get(k), b[k]) if k in b else a[k] for k in {**a, **b}}


def _http(status, body=None, content_type="application/json"):
    if body is None:
        # An empty body is read from the stream, as from a real connection.
        raw = urllib3.HTTPResponse(
            body=io.BytesIO(b""), status=status, preload_content=False
        )
    else:
        raw = urllib3.HTTPResponse(
            body=json.dumps(body).encode(),
            status=status,
            headers={"Content-Type": content_type},
            preload_content=True,
        )
    return RESTResponse(raw)


def ok(model, body, status=200):
    """A response whose body, an object or a list of objects, is validated against model."""
    for item in body if isinstance(body, list) else [body]:
        parsed = model.from_dict(item)
        # model_dump keeps read-only fields; to_dict sees through oneOf wrappers.
        dumped = _merge(
            parsed.model_dump(by_alias=True, exclude_none=True, mode="json"),
            parsed.to_dict(),
        )
        _assert_known_keys(item, dumped)
    return _http(status, body)


def created(model, body):
    return ok(model, body, status=201)


def no_content():
    return _http(204)


def error(status, reason="internal", detail="error"):
    problem = {
        "type": PROBLEMS + reason,
        "title": "error",
        "status": status,
        "detail": detail,
    }
    return _http(status, problem, "application/problem+json")


def network(net_id, name, net_type="NETWORK_TYPE_GENEVE", segmentation_id=None):
    net = {
        "networkId": net_id,
        "networkName": name,
        "subnetIds": ["a3bae246-4726-4312-bd06-47b80d34795a"],
        "networkType": net_type,
        "operationalState": "OPERATIONAL_STATE_ENABLED",
    }
    if net_type != "NETWORK_TYPE_GENEVE":
        net["providerNetwork"] = "mx5p0"
    if segmentation_id is not None:
        net["segmentationId"] = segmentation_id
    return net


def flavour(flavour_id=FLAVOUR_ID, name="small", memory="2048M", cpus=2, disk="10Gi"):
    return {
        "flavourId": flavour_id,
        "flavourName": name,
        "virtualMemory": {"virtualMemSize": memory},
        "virtualCpu": {"numVirtualCpu": cpus},
        "storageAttributes": [
            {
                "typeOfStorage": "TYPE_OF_STORAGE_VOLUME",
                "sizeOfStorage": disk,
                "isBoot": True,
            }
        ],
    }


def image(image_id, name, location="https://images.test/disk.qcow2"):
    return {
        "imageId": image_id,
        "name": name,
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-01T00:00:00Z",
        "size": "1Gi",
        "status": "IMAGE_STATUS_AVAILABLE",
        "source": {"http": {"url": location}},
    }


def nic(name, net_id=None, mgmt=False, ready=True, ip=None, mac=None, pci=None):
    iface = {
        "name": name,
        "computeId": VM_ID,
        "typeVirtualNic": (
            "TYPE_VIRTUAL_NIC_MASQUERADE"
            if mgmt
            else "TYPE_VIRTUAL_NIC_SRIOV" if pci else "TYPE_VIRTUAL_NIC_BRIDGE"
        ),
        "operationalState": (
            "OPERATIONAL_STATE_ENABLED" if ready else "OPERATIONAL_STATE_DISABLED"
        ),
    }
    if mgmt:
        iface["isManagement"] = True
    if net_id:
        iface["networkId"] = net_id
    if ip:
        iface["ipAddresses"] = [ip]
    if mac:
        iface["macAddress"] = mac
    if pci:
        iface["hostPciAddress"] = pci
    return iface


def compute(state="COMPUTE_RUNNING_STATE_STARTED", nics=(), detail=None):
    vm = {
        "computeId": VM_ID,
        "computeName": "vm",
        "flavourId": FLAVOUR_ID,
        "imageId": IMAGE_ID,
        "networkInterfaces": list(nics),
        "hostId": "node-1",
        "operationalState": "OPERATIONAL_STATE_ENABLED",
        "runningState": state,
        "metadata": {"kubevim.kubenfv.io/vm-name": f"vm-{VM_ID}"},
    }
    if detail:
        vm["statusDetail"] = detail
    return vm


def networks(*nets):
    return ok(Network, list(nets))


def flavours(*items):
    return ok(Flavour, list(items))


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


class TestHelpers(unittest.TestCase):
    def test_quantity_suffixes(self):
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

    def test_quantity_invalid(self):
        for quantity in ("", "Gi", "10Xi", "ten"):
            with self.subTest(quantity=quantity):
                with self.assertRaises(vimconn.VimConnUnexpectedResponse):
                    quantity_to_bytes(quantity)

    def test_split_physical_network(self):
        cases = {
            "mx5p0": ("mx5p0", None),
            "mx5p0/mlx_vf_pf0_vfio": ("mx5p0", "openshift.io/mlx_vf_pf0_vfio"),
            "mx5p0/example.com/vf": ("mx5p0", "example.com/vf"),
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(split_physical_network(value), expected)


class TestErrorMapping(KubevimTestCase):
    def test_connectivity_ok(self):
        self.respond(flavours())
        self.assertIsNone(self.conn.check_vim_connectivity())
        self.assertEqual(self.sent(), ("GET", "/flavour/v1/flavours", {}, None))

    def test_http_errors(self):
        cases = {
            (400, "invalid-filter"): vimconn.VimConnException,
            (401, "x"): vimconn.VimConnAuthException,
            (403, "x"): vimconn.VimConnAuthException,
            (404, "not-found"): vimconn.VimConnNotFoundException,
            (409, "invalid-state"): vimconn.VimConnConflictException,
            (422, "validation-failed"): vimconn.VimConnException,
            (422, "unsupported-field"): vimconn.VimConnNotSupportedException,
            (501, "not-implemented"): vimconn.VimConnNotSupportedException,
            (500, "internal"): vimconn.VimConnConnectionException,
            (503, "backend-unavailable"): vimconn.VimConnConnectionException,
        }
        for (status, reason), exception in cases.items():
            with self.subTest(status=status, reason=reason):
                self.respond(error(status, reason, detail="the reason"))
                with self.assertRaises(exception) as ctx:
                    self.conn.check_vim_connectivity()
                self.assertIs(type(ctx.exception), exception)
                self.assertIn("the reason", str(ctx.exception))

    def test_error_without_problem_body(self):
        self.respond(_http(502, None, "text/plain"))
        with self.assertRaises(vimconn.VimConnConnectionException):
            self.conn.check_vim_connectivity()

    def test_gateway_unreachable(self):
        self.request.side_effect = urllib3.exceptions.MaxRetryError(None, URL)
        with self.assertRaises(vimconn.VimConnConnectionException):
            self.conn.check_vim_connectivity()

    def test_log_level(self):
        conn = vimconnector("vim-uuid", "kubevim", None, None, URL, log_level="DEBUG")
        self.assertEqual(conn.logger.level, logging.DEBUG)


ISSUER = "https://idp.test/realms/nfv"
TOKEN_URL = ISSUER + "/protocol/openid-connect/token"


def idp(status, body):
    return urllib3.HTTPResponse(
        body=json.dumps(body).encode(),
        status=status,
        headers={"Content-Type": "application/json"},
        preload_content=True,
    )


def token(value, expires_in=300):
    return idp(
        200, {"access_token": value, "token_type": "Bearer", "expires_in": expires_in}
    )


class TestAuth(KubevimTestCase):
    """OAuth 2.0 client credentials against the IdP, whose HTTP layer is mocked."""

    def setUp(self):
        super().setUp()
        patcher = patch.object(urllib3.PoolManager, "request", autospec=True)
        self.idp = patcher.start()
        self.addCleanup(patcher.stop)

    def connect(self, user="osm-ro", passwd="s3cret", **config):
        return vimconnector(
            "vim-uuid",
            "kubevim",
            None,
            None,
            URL,
            user=user,
            passwd=passwd,
            config=config,
        )

    def authorization(self, index=-1):
        return self.request.call_args_list[index].kwargs["headers"].get("Authorization")

    def test_no_auth_without_token_endpoint(self):
        self.respond(flavours())
        self.conn.check_vim_connectivity()
        self.assertIsNone(self.authorization())
        self.idp.assert_not_called()

    def test_token_request(self):
        self.idp.side_effect = [token("t1")]
        self.respond(flavours())
        self.connect(token_url=TOKEN_URL).check_vim_connectivity()
        self.assertEqual(self.authorization(), "Bearer t1")
        call = self.idp.call_args
        self.assertEqual(call.args[1:], ("POST", TOKEN_URL))
        self.assertEqual(call.kwargs["fields"], {"grant_type": "client_credentials"})
        self.assertFalse(call.kwargs["encode_multipart"])
        basic = base64.b64encode(b"osm-ro:s3cret").decode()
        self.assertEqual(call.kwargs["headers"]["Authorization"], f"Basic {basic}")

    def test_scope(self):
        self.idp.side_effect = [token("t1")]
        self.respond(flavours())
        self.connect(token_url=TOKEN_URL, scope="kubevim").check_vim_connectivity()
        self.assertEqual(self.idp.call_args.kwargs["fields"]["scope"], "kubevim")

    def test_credentials_are_form_encoded(self):
        self.idp.side_effect = [token("t1")]
        self.respond(flavours())
        conn = self.connect(user="a:b", passwd="p@ss w", token_url=TOKEN_URL)
        conn.check_vim_connectivity()
        basic = base64.b64encode(b"a%3Ab:p%40ss+w").decode()
        self.assertEqual(
            self.idp.call_args.kwargs["headers"]["Authorization"], f"Basic {basic}"
        )

    def test_token_cached(self):
        self.idp.side_effect = [token("t1")]
        self.respond(flavours(), flavours())
        conn = self.connect(token_url=TOKEN_URL)
        conn.check_vim_connectivity()
        conn.check_vim_connectivity()
        self.assertEqual(self.idp.call_count, 1)
        self.assertEqual(self.authorization(), "Bearer t1")

    def test_token_refreshed_before_expiry(self):
        self.idp.side_effect = [token("t1", expires_in=300), token("t2")]
        self.respond(flavours(), flavours(), flavours())
        conn = self.connect(token_url=TOKEN_URL)
        with patch("time.monotonic", side_effect=[1000.0, 1269.0, 1271.0, 1271.0]):
            conn.check_vim_connectivity()
            conn.check_vim_connectivity()
            self.assertEqual(self.authorization(), "Bearer t1")
            conn.check_vim_connectivity()
        self.assertEqual(self.authorization(), "Bearer t2")
        self.assertEqual(self.idp.call_count, 2)

    def test_token_without_expiry_is_kept(self):
        self.idp.side_effect = [
            idp(200, {"access_token": "t1", "token_type": "Bearer"})
        ]
        self.respond(flavours(), flavours())
        conn = self.connect(token_url=TOKEN_URL)
        conn.check_vim_connectivity()
        conn.check_vim_connectivity()
        self.assertEqual(self.idp.call_count, 1)

    def test_rejected_token_is_refreshed_once(self):
        self.idp.side_effect = [token("t1"), token("t2")]
        self.respond(error(401), flavours())
        self.connect(token_url=TOKEN_URL).check_vim_connectivity()
        self.assertEqual(self.authorization(0), "Bearer t1")
        self.assertEqual(self.authorization(1), "Bearer t2")
        self.assertEqual(self.sent(1), ("GET", "/flavour/v1/flavours", {}, None))

    def test_rejected_again_raises(self):
        self.idp.side_effect = [token("t1"), token("t2")]
        self.respond(error(401), error(401))
        with self.assertRaises(vimconn.VimConnAuthException):
            self.connect(token_url=TOKEN_URL).check_vim_connectivity()
        self.assertEqual(self.request.call_count, 2)

    def test_missing_scope_is_not_retried(self):
        self.idp.side_effect = [token("t1")]
        self.respond(error(403))
        with self.assertRaises(vimconn.VimConnAuthException):
            self.connect(token_url=TOKEN_URL).check_vim_connectivity()
        self.assertEqual(self.request.call_count, 1)

    def test_bad_client_credentials(self):
        for status in (400, 401):
            with self.subTest(status=status):
                self.idp.side_effect = [idp(status, {"error": "invalid_client"})]
                with self.assertRaises(vimconn.VimConnAuthException):
                    self.connect(token_url=TOKEN_URL).check_vim_connectivity()
        self.request.assert_not_called()

    def test_idp_server_error(self):
        self.idp.side_effect = [idp(503, {})]
        with self.assertRaises(vimconn.VimConnConnectionException):
            self.connect(token_url=TOKEN_URL).check_vim_connectivity()

    def test_idp_unreachable(self):
        self.idp.side_effect = urllib3.exceptions.MaxRetryError(None, TOKEN_URL)
        with self.assertRaises(vimconn.VimConnConnectionException):
            self.connect(token_url=TOKEN_URL).check_vim_connectivity()

    def test_token_response_without_token(self):
        for body in ({"token_type": "Bearer"}, ["not", "an", "object"]):
            with self.subTest(body=body):
                self.idp.side_effect = [idp(200, body)]
                with self.assertRaises(vimconn.VimConnUnexpectedResponse):
                    self.connect(token_url=TOKEN_URL).check_vim_connectivity()

    def test_issuer_discovery(self):
        self.idp.side_effect = [
            idp(200, {"issuer": ISSUER, "token_endpoint": TOKEN_URL}),
            token("t1", expires_in=0),
            token("t2"),
        ]
        self.respond(flavours(), flavours())
        conn = self.connect(issuer=ISSUER + "/")
        conn.check_vim_connectivity()
        conn.check_vim_connectivity()
        urls = [(c.args[1], c.args[2]) for c in self.idp.call_args_list]
        self.assertEqual(
            urls,
            [
                ("GET", ISSUER + "/.well-known/openid-configuration"),
                ("POST", TOKEN_URL),
                ("POST", TOKEN_URL),
            ],
        )
        self.assertEqual(self.authorization(), "Bearer t2")

    def test_discovery_without_token_endpoint(self):
        self.idp.side_effect = [idp(200, {"issuer": ISSUER})]
        with self.assertRaises(vimconn.VimConnUnexpectedResponse):
            self.connect(issuer=ISSUER).check_vim_connectivity()

    def test_token_url_wins_over_issuer(self):
        self.idp.side_effect = [token("t1")]
        self.respond(flavours())
        self.connect(token_url=TOKEN_URL, issuer=ISSUER).check_vim_connectivity()
        self.assertEqual(self.idp.call_count, 1)
        self.assertEqual(self.idp.call_args.args[2], TOKEN_URL)

    def test_credentials_required(self):
        for user, passwd in ((None, "s3cret"), ("osm-ro", None), ("", "")):
            with self.subTest(user=user, passwd=passwd):
                with self.assertRaises(vimconn.VimConnException):
                    self.connect(user=user, passwd=passwd, token_url=TOKEN_URL)

    def test_ca_cert(self):
        conn = self.connect(token_url=TOKEN_URL, ca_cert="/etc/ro/ca.pem")
        self.assertEqual(conn.configuration.ssl_ca_cert, "/etc/ro/ca.pem")
        self.assertEqual(
            conn._idp_http.connection_pool_kw["ca_certs"], "/etc/ro/ca.pem"
        )
        self.assertEqual(
            conn._idp_http.connection_pool_kw["cert_reqs"], "CERT_REQUIRED"
        )

    def test_insecure(self):
        conn = self.connect(token_url=TOKEN_URL, insecure=True)
        self.assertFalse(conn.configuration.verify_ssl)
        self.assertEqual(conn._idp_http.connection_pool_kw["cert_reqs"], "CERT_NONE")

    def test_insecure_and_ca_cert_exclusive(self):
        with self.assertRaises(vimconn.VimConnException):
            self.connect(token_url=TOKEN_URL, insecure=True, ca_cert="/etc/ro/ca.pem")

    def test_secret_and_token_not_logged(self):
        self.respond(error(401), flavours())
        self.idp.side_effect = [token("tok-value"), token("tok-value-2")]
        conn = vimconnector(
            "vim-uuid",
            "kubevim",
            None,
            None,
            URL,
            user="osm-ro",
            passwd="s3cret",
            log_level="DEBUG",
            config={"token_url": TOKEN_URL},
        )
        with self.assertLogs("ro.vim.kubevim", level="DEBUG") as logs:
            conn.check_vim_connectivity()
        output = "\n".join(logs.output)
        self.assertIn("osm-ro", output)
        for secret in ("s3cret", "tok-value"):
            self.assertNotIn(secret, output)


class TestNewNetwork(KubevimTestCase):
    def create(self, *args, **kwargs):
        """Creates a network and returns the network sent to Kube-VIM."""
        self.respond(created(Network, network(NET_ID, "net")))
        net_id, extra = self.conn.new_network(*args, **kwargs)
        self.assertEqual((net_id, extra), (NET_ID, {}))
        method, path, _, body = self.sent()
        self.assertEqual((method, path), ("POST", "/network/v1/networks"))
        return body["network"]

    def test_overlay(self):
        ip_profile = {
            "ip_version": "IPv4",
            "subnet_address": "10.0.0.0/24",
            "gateway_address": "10.0.0.1",
            "dhcp_enabled": True,
        }
        net = self.create("net", "bridge", ip_profile=ip_profile, shared=True)
        self.assertEqual(
            net,
            {
                "networkName": "net",
                "networkType": "NETWORK_TYPE_GENEVE",
                "layer3Attributes": [
                    {
                        "ipVersion": "IP_VERSION_IPV4",
                        "cidr": "10.0.0.0/24",
                        "gatewayIp": "10.0.0.1",
                        "isDhcpEnabled": True,
                    }
                ],
            },
        )

    def test_ipv6_and_dhcp_default(self):
        net = self.create(
            "net",
            "bridge",
            ip_profile={"ip_version": "IPv6", "subnet_address": "fd00::/64"},
        )
        self.assertEqual(
            net["layer3Attributes"],
            [
                {
                    "ipVersion": "IP_VERSION_IPV6",
                    "cidr": "fd00::/64",
                    "isDhcpEnabled": True,
                }
            ],
        )

    def test_gateway_none(self):
        net = self.create(
            "net",
            "bridge",
            ip_profile={"subnet_address": "10.0.0.0/24", "gateway_address": None},
        )
        self.assertNotIn("gatewayIp", net["layer3Attributes"][0])

    def test_dhcp_disabled_as_string(self):
        net = self.create(
            "net",
            "bridge",
            ip_profile={"subnet_address": "10.0.0.0/24", "dhcp_enabled": "false"},
        )
        self.assertFalse(net["layer3Attributes"][0]["isDhcpEnabled"])

    def test_random_subnet_without_ip_profile(self):
        net = self.create("net", "bridge")
        cidr = net["layer3Attributes"][0]["cidr"]
        self.assertRegex(cidr, r"^192\.168\.\d{1,3}\.0/24$")

    def test_vlan(self):
        net = self.create(
            "net",
            "data",
            ip_profile={"subnet_address": "10.0.0.0/24"},
            provider_network_profile={
                "physical-network": "mx5p0",
                "segmentation-id": "100",
            },
        )
        self.assertEqual(net["networkType"], "NETWORK_TYPE_VLAN")
        self.assertEqual(net["providerNetwork"], "mx5p0")
        self.assertEqual(net["segmentationId"], 100)
        self.assertNotIn("sriov", net)
        self.assertEqual(len(net["layer3Attributes"]), 1)

    def test_flat_alternative_keys(self):
        net = self.create(
            "net",
            "data",
            provider_network_profile={
                "provider_network": "mx5p0",
                "segmentation_id": 0,
            },
        )
        self.assertEqual(net["networkType"], "NETWORK_TYPE_FLAT")
        self.assertNotIn("segmentationId", net)

    def test_vlan_with_pool_takes_both_interface_kinds(self):
        net = self.create(
            "net",
            "data",
            ip_profile={"subnet_address": "10.0.0.0/24"},
            provider_network_profile={
                "physical-network": "mx5p0/mlx_vf_pf0_vfio",
                "segmentation-id": "100",
            },
        )
        self.assertEqual(net["providerNetwork"], "mx5p0")
        self.assertEqual(net["sriov"], {"pool": "openshift.io/mlx_vf_pf0_vfio"})
        self.assertEqual(len(net["layer3Attributes"]), 1)

    def test_sriov_network_type_has_no_subnet(self):
        net = self.create(
            "net",
            "data",
            provider_network_profile={
                "physical-network": "mx5p0/mlx_vf_pf0_vfio",
                "network-type": "sriov",
            },
        )
        self.assertEqual(net["networkType"], "NETWORK_TYPE_FLAT")
        self.assertEqual(net["sriov"], {"pool": "openshift.io/mlx_vf_pf0_vfio"})
        self.assertNotIn("layer3Attributes", net)

    def test_rejected_profiles(self):
        cases = {
            "no profile": ("data", None),
            "sriov without pool": (
                "data",
                {"physical-network": "mx5p0", "network-type": "sriov"},
            ),
            "no physical network": ("data", {"segmentation-id": "100"}),
        }
        for name, (net_type, profile) in cases.items():
            with self.subTest(name):
                with self.assertRaises(vimconn.VimConnNotSupportedException):
                    self.conn.new_network(
                        "net", net_type, provider_network_profile=profile
                    )
        self.request.assert_not_called()

    def test_api_error(self):
        self.respond(error(422, "validation-failed"))
        with self.assertRaises(vimconn.VimConnException):
            self.conn.new_network("net", "bridge")


class TestNetworkQueries(KubevimTestCase):
    def test_list_without_filter(self):
        self.respond(networks(network(NET_ID, "net-a")))
        nets = self.conn.get_network_list()
        self.assertEqual(self.sent(), ("GET", "/network/v1/networks", {}, None))
        self.assertEqual(len(nets), 1)
        self.assertEqual(nets[0]["id"], NET_ID)
        self.assertEqual(nets[0]["name"], "net-a")
        self.assertEqual(nets[0]["status"], "ACTIVE")
        self.assertFalse(nets[0]["shared"])

    def test_list_filters(self):
        self.respond(networks())
        self.conn.get_network_list({"name": "it's mgmt", "id": NET_ID, "shared": False})
        _, _, query, _ = self.sent()
        self.assertEqual(
            query["filter"], f"(eq,networkName,'it''s mgmt');(eq,networkId,'{NET_ID}')"
        )

    def test_list_shared_is_empty(self):
        self.assertEqual(self.conn.get_network_list({"shared": True}), [])
        self.request.assert_not_called()

    def test_list_unsupported_filter(self):
        with self.assertRaises(vimconn.VimConnNotSupportedException):
            self.conn.get_network_list({"tenant_id": "x"})

    def test_network_types(self):
        cases = [
            (network(NET_ID, "a"), "vxlan", 0),
            (network(NET_ID, "b", "NETWORK_TYPE_VLAN", 100), "vlan", 100),
            (network(NET_ID, "c", "NETWORK_TYPE_FLAT"), "flat", None),
        ]
        for body, net_type, segmentation_id in cases:
            with self.subTest(net_type=net_type):
                self.respond(networks(body))
                net = self.conn.get_network_list()[0]
                self.assertEqual(net["network_type"], net_type)
                self.assertEqual(net.get("segmentation_id"), segmentation_id)

    def test_get_network(self):
        self.respond(ok(Network, network(NET_ID, "net-a")))
        net = self.conn.get_network(NET_ID)
        self.assertEqual(
            self.sent(), ("GET", f"/network/v1/networks/{NET_ID}", {}, None)
        )
        self.assertEqual(net["id"], NET_ID)
        self.assertNotIn("networkId", net)

    def test_get_network_disabled(self):
        body = network(NET_ID, "net-a")
        body["operationalState"] = "OPERATIONAL_STATE_DISABLED"
        self.respond(ok(Network, body))
        self.assertEqual(self.conn.get_network(NET_ID)["status"], "INACTIVE")

    def test_get_network_not_found(self):
        self.respond(error(404, "not-found"))
        with self.assertRaises(vimconn.VimConnNotFoundException):
            self.conn.get_network(NET_ID)

    def test_delete_network(self):
        self.respond(no_content())
        self.assertEqual(self.conn.delete_network(NET_ID), NET_ID)
        self.assertEqual(
            self.sent(), ("DELETE", f"/network/v1/networks/{NET_ID}", {}, None)
        )

    def test_delete_network_not_found(self):
        self.respond(error(404, "not-found"))
        with self.assertRaises(vimconn.VimConnNotFoundException):
            self.conn.delete_network(NET_ID)

    def test_refresh_nets_status(self):
        self.respond(networks(network(NET_ID, "net-a")))
        res = self.conn.refresh_nets_status([NET_ID, NET_ID_2])
        self.assertEqual(res[NET_ID]["status"], "ACTIVE")
        self.assertEqual(yaml.safe_load(res[NET_ID]["vim_info"])["name"], "net-a")
        self.assertEqual(res[NET_ID_2], {"status": "DELETED"})

    def test_refresh_nets_status_unreachable(self):
        self.respond(error(503, "backend-unavailable"))
        res = self.conn.refresh_nets_status([NET_ID])
        self.assertEqual(res[NET_ID]["status"], "VIM_ERROR")


class TestFlavors(KubevimTestCase):
    def test_get_flavor(self):
        self.respond(ok(Flavour, flavour()))
        self.assertEqual(
            self.conn.get_flavor(FLAVOUR_ID),
            {"id": FLAVOUR_ID, "name": "small", "ram": 2048, "vcpus": 2, "disk": 10},
        )
        self.assertEqual(
            self.sent(), ("GET", f"/flavour/v1/flavours/{FLAVOUR_ID}", {}, None)
        )

    def test_get_flavor_canonical_quantities(self):
        self.respond(ok(Flavour, flavour(memory="2G", disk="10Gi")))
        flavor = self.conn.get_flavor(FLAVOUR_ID)
        self.assertEqual((flavor["ram"], flavor["disk"]), (2000, 10))

    def test_get_flavor_by_name_not_supported(self):
        with self.assertRaises(vimconn.VimConnNotSupportedException):
            self.conn.get_flavor(flavor_name="small")

    def test_get_flavor_not_found(self):
        self.respond(error(404, "not-found"))
        with self.assertRaises(vimconn.VimConnNotFoundException):
            self.conn.get_flavor(FLAVOUR_ID)

    def test_get_flavor_without_boot_storage(self):
        body = flavour()
        body["storageAttributes"][0]["isBoot"] = False
        self.respond(ok(Flavour, body))
        with self.assertRaises(vimconn.VimConnUnexpectedResponse):
            self.conn.get_flavor(FLAVOUR_ID)

    def test_new_flavor(self):
        self.respond(created(Flavour, flavour()))
        flavor_id = self.conn.new_flavor(
            {"name": "small", "ram": 2048, "vcpus": 2, "disk": 10}
        )
        self.assertEqual(flavor_id, FLAVOUR_ID)
        method, path, _, body = self.sent()
        self.assertEqual((method, path), ("POST", "/flavour/v1/flavours"))
        self.assertEqual(
            body,
            {
                "flavour": {
                    "flavourName": "small",
                    "virtualMemory": {"virtualMemSize": "2048M"},
                    "virtualCpu": {"numVirtualCpu": 2},
                    "storageAttributes": [
                        {
                            "typeOfStorage": "TYPE_OF_STORAGE_VOLUME",
                            "sizeOfStorage": "10Gi",
                            "isBoot": True,
                        }
                    ],
                }
            },
        )

    def test_new_flavor_api_error(self):
        self.respond(error(422, "unsupported-field"))
        with self.assertRaises(vimconn.VimConnNotSupportedException):
            self.conn.new_flavor({"name": "small", "ram": 2048, "vcpus": 2, "disk": 10})

    def test_delete_flavor(self):
        self.respond(no_content())
        self.assertEqual(self.conn.delete_flavor(FLAVOUR_ID), FLAVOUR_ID)
        self.assertEqual(
            self.sent(), ("DELETE", f"/flavour/v1/flavours/{FLAVOUR_ID}", {}, None)
        )

    def test_delete_flavor_not_found(self):
        self.respond(error(404, "not-found"))
        with self.assertRaises(vimconn.VimConnNotFoundException):
            self.conn.delete_flavor(FLAVOUR_ID)

    def test_get_flavor_id_from_data(self):
        self.respond(flavours(flavour()))
        flavor_id = self.conn.get_flavor_id_from_data(
            {"ram": 2048, "vcpus": 2, "disk": 10}
        )
        self.assertEqual(flavor_id, FLAVOUR_ID)
        _, path, query, _ = self.sent()
        self.assertEqual(path, "/flavour/v1/flavours")
        self.assertEqual(
            query["filter"],
            "(eq,virtualMemory/virtualMemSize,2048M);(eq,virtualCpu/numVirtualCpu,2);"
            "(eq,storageAttributes/sizeOfStorage,10Gi)",
        )

    def test_get_flavor_id_from_data_not_found(self):
        self.respond(flavours())
        with self.assertRaises(vimconn.VimConnNotFoundException):
            self.conn.get_flavor_id_from_data({"ram": 2048, "vcpus": 2, "disk": 10})


class TestImages(KubevimTestCase):
    def test_list(self):
        self.respond(ok(Image, [image(IMAGE_ID, "cirros")]))
        images = self.conn.get_image_list()
        self.assertEqual(self.sent(), ("GET", "/image/v1/images", {}, None))
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]["id"], IMAGE_ID)
        self.assertEqual(images[0]["name"], "cirros")
        self.assertEqual(images[0]["location"], "https://images.test/disk.qcow2")
        self.assertEqual(images[0]["status"], "IMAGE_STATUS_AVAILABLE")
        self.assertEqual(
            images[0]["source"], {"http": {"url": "https://images.test/disk.qcow2"}}
        )

    def test_filters(self):
        self.respond(ok(Image, []))
        self.conn.get_image_list(
            {
                "id": IMAGE_ID,
                "name": "cirros 0.6",
                "location": "https://images.test/a.img",
            }
        )
        _, _, query, _ = self.sent()
        self.assertEqual(
            query["filter"],
            f"(eq,imageId,'{IMAGE_ID}');(eq,name,'cirros 0.6');"
            "(eq,source/http/url,'https://images.test/a.img')",
        )

    def test_checksum_not_implemented(self):
        with self.assertRaises(vimconn.VimConnNotImplemented):
            self.conn.get_image_list({"checksum": "abc"})

    def test_api_error(self):
        self.respond(error(400, "invalid-filter"))
        with self.assertRaises(vimconn.VimConnException):
            self.conn.get_image_list({"name": "cirros"})


class TestNewVminstance(KubevimTestCase):
    def create(self, net_list, response_nics, **kwargs):
        self.respond(created(Compute, compute(nics=response_nics)))
        args = dict(
            name="vm",
            description="",
            start=True,
            image_id=IMAGE_ID,
            flavor_id=FLAVOUR_ID,
            affinity_group_list=[],
            net_list=net_list,
        )
        args.update(kwargs)
        vm_id, extra = self.conn.new_vminstance(**args)
        self.assertEqual((vm_id, extra), (VM_ID, {}))
        method, path, _, body = self.sent()
        self.assertEqual((method, path), ("POST", "/compute/v1/computes"))
        return body

    def test_interfaces(self):
        net_list = [
            {
                "net_id": NET_ID,
                "type": "virtual",
                "ip_address": "10.0.0.5",
                "mac_address": "02:00:00:00:00:01",
                "bw": 1,
            },
            {"net_id": NET_ID, "type": "virtual"},
            {"net_id": NET_ID_2, "type": "SR-IOV", "ip_address": "10.1.0.5"},
        ]
        body = self.create(
            net_list,
            [
                nic("default", mgmt=True),
                nic("nic0", NET_ID),
                nic("nic1", NET_ID),
                nic("nic2", NET_ID_2, pci="0000:b3:00.2"),
            ],
        )
        self.assertEqual(
            body["compute"],
            {"computeName": "vm", "flavourId": FLAVOUR_ID, "imageId": IMAGE_ID},
        )
        self.assertEqual(
            body["networkInterfaces"],
            [
                {
                    "name": "nic0",
                    "networkId": NET_ID,
                    "typeVirtualNic": "TYPE_VIRTUAL_NIC_BRIDGE",
                    "ipAssignment": "IP_ASSIGNMENT_STATIC",
                    "ipAddresses": ["10.0.0.5"],
                    "macAddress": "02:00:00:00:00:01",
                },
                {
                    "name": "nic1",
                    "networkId": NET_ID,
                    "typeVirtualNic": "TYPE_VIRTUAL_NIC_BRIDGE",
                },
                {
                    "name": "nic2",
                    "networkId": NET_ID_2,
                    "typeVirtualNic": "TYPE_VIRTUAL_NIC_SRIOV",
                    "ipAssignment": "IP_ASSIGNMENT_NONE",
                },
            ],
        )
        self.assertNotIn("start", body)
        self.assertEqual([net["vim_id"] for net in net_list], ["nic0", "nic1", "nic2"])

    def test_vf_types(self):
        for nic_type in ("SR-IOV", "VF", "VFnotShared"):
            with self.subTest(nic_type=nic_type):
                body = self.create(
                    [{"net_id": NET_ID, "type": nic_type}], [nic("nic0", NET_ID)]
                )
                self.assertEqual(
                    body["networkInterfaces"][0]["typeVirtualNic"],
                    "TYPE_VIRTUAL_NIC_SRIOV",
                )

    def test_user_data_and_start(self):
        with patch.object(
            vimconnector, "_create_user_data", return_value=(None, "#cloud-config\n")
        ):
            body = self.create([], [], cloud_config={"users": []}, start=False)
        self.assertEqual(
            body["userData"],
            {
                "content": "#cloud-config\n",
                "method": "USER_DATA_TRANSPORTATION_METHOD_NO_CLOUD",
            },
        )
        self.assertIs(body["start"], False)

    def test_rejected_interfaces(self):
        for nic_type in ("PCI-PASSTHROUGH", "PF", "unknown"):
            with self.subTest(nic_type=nic_type):
                with self.assertRaises(vimconn.VimConnNotSupportedException):
                    self.conn.new_vminstance(
                        "vm",
                        "",
                        True,
                        IMAGE_ID,
                        FLAVOUR_ID,
                        [],
                        [{"net_id": NET_ID, "type": nic_type}],
                    )
        self.request.assert_not_called()

    def test_api_error(self):
        self.respond(error(409, "invalid-state", "software image is not available"))
        with self.assertRaises(vimconn.VimConnConflictException) as ctx:
            self.conn.new_vminstance("vm", "", True, IMAGE_ID, FLAVOUR_ID, [], [])
        self.assertIn("software image is not available", str(ctx.exception))


class TestVminstance(KubevimTestCase):
    def test_get_vminstance(self):
        self.respond(ok(Compute, compute(nics=[nic("nic0", NET_ID, ip="10.0.0.5")])))
        vm = self.conn.get_vminstance(VM_ID)
        self.assertEqual(
            self.sent(), ("GET", f"/compute/v1/computes/{VM_ID}", {}, None)
        )
        self.assertEqual(vm["computeId"], VM_ID)
        self.assertEqual(vm["runningState"], "COMPUTE_RUNNING_STATE_STARTED")
        self.assertEqual(
            vm["networkInterfaces"][0]["typeVirtualNic"], "TYPE_VIRTUAL_NIC_BRIDGE"
        )

    def test_get_vminstance_not_found(self):
        self.respond(error(404, "not-found"))
        with self.assertRaises(vimconn.VimConnNotFoundException):
            self.conn.get_vminstance(VM_ID)

    def test_delete_vminstance(self):
        self.respond(no_content())
        self.assertEqual(self.conn.delete_vminstance(VM_ID), VM_ID)
        self.assertEqual(
            self.sent(), ("DELETE", f"/compute/v1/computes/{VM_ID}", {}, None)
        )

    def test_delete_vminstance_not_found(self):
        self.respond(error(404, "not-found"))
        with self.assertRaises(vimconn.VimConnNotFoundException):
            self.conn.delete_vminstance(VM_ID)

    def test_action_not_supported(self):
        with self.assertRaises(vimconn.VimConnNotSupportedException):
            self.conn.action_vminstance(VM_ID, {"start": None})


class TestRefreshVmsStatus(KubevimTestCase):
    def refresh(self, body):
        self.respond(ok(Compute, body))
        return self.conn.refresh_vms_status([VM_ID])[VM_ID]

    def test_active(self):
        res = self.refresh(
            compute(
                nics=[
                    nic("default", mgmt=True, ip="10.16.0.5", mac="02:00:00:00:00:00"),
                    nic("nic0", NET_ID, ip="10.0.0.5", mac="02:00:00:00:00:01"),
                    nic("nic1", NET_ID_2, mac="02:00:00:00:00:02", pci="0000:b3:00.2"),
                ]
            )
        )
        self.assertEqual(res["status"], "ACTIVE")
        self.assertEqual(yaml.safe_load(res["vim_info"])["computeId"], VM_ID)
        mgmt, bridge, vf = res["interfaces"]
        self.assertEqual(mgmt["vim_net_id"], "management")
        self.assertEqual(
            {k: v for k, v in bridge.items() if k != "vim_info"},
            {
                "mac_address": "02:00:00:00:00:01",
                "ip_address": "10.0.0.5",
                "vim_interface_id": "nic0",
                "vim_net_id": NET_ID,
                "compute_node": "node-1",
            },
        )
        self.assertEqual(vf["pci"], "0000:b3:00.2")
        self.assertIsNone(vf["ip_address"])

    def test_interface_not_ready_is_build(self):
        res = self.refresh(compute(nics=[nic("nic0", NET_ID, ready=False)]))
        self.assertEqual(res["status"], "BUILD")
        self.assertEqual(res["interfaces"], [])

    def test_running_states(self):
        cases = {
            "COMPUTE_RUNNING_STATE_STARTED": "ACTIVE",
            "COMPUTE_RUNNING_STATE_MIGRATING": "ACTIVE",
            "COMPUTE_RUNNING_STATE_PAUSED": "PAUSED",
            "COMPUTE_RUNNING_STATE_STARTING": "BUILD",
            "COMPUTE_RUNNING_STATE_STOPPING": "INACTIVE",
            "COMPUTE_RUNNING_STATE_STOPPED": "INACTIVE",
            "COMPUTE_RUNNING_STATE_TERMINATING": "INACTIVE",
        }
        for state, status in cases.items():
            with self.subTest(state=state):
                self.assertEqual(self.refresh(compute(state=state))["status"], status)

    def test_unknown_state(self):
        res = self.refresh(compute(state="COMPUTE_RUNNING_STATE_UNSPECIFIED"))
        self.assertEqual(res["status"], "OTHER")
        self.assertIn("UNSPECIFIED", res["error_msg"])

    def test_failed(self):
        res = self.refresh(
            compute(state="COMPUTE_RUNNING_STATE_FAILED", detail="ErrImagePull")
        )
        self.assertEqual(res, {"status": "ERROR", "error_msg": "ErrImagePull"})

    def test_failed_without_detail(self):
        res = self.refresh(compute(state="COMPUTE_RUNNING_STATE_FAILED"))
        self.assertEqual(res["error_msg"], "unknown")

    def test_deleted(self):
        self.respond(error(404, "not-found"))
        res = self.conn.refresh_vms_status([VM_ID])
        self.assertEqual(res[VM_ID]["status"], "DELETED")

    def test_unreachable(self):
        self.respond(error(503, "backend-unavailable"))
        res = self.conn.refresh_vms_status([VM_ID])
        self.assertEqual(res[VM_ID]["status"], "VIM_ERROR")


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
