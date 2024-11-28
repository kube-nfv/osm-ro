# -*- coding: utf-8 -*-

##
# Copyright 2017 Intel Corporation.
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
This module contains unit tests for the OpenStack VIM connector
Run this directly with python2 or python3.
"""
from copy import deepcopy
import logging
import unittest

import cinderclient.exceptions as cExceptions
from mock import MagicMock, patch
from neutronclient.common import exceptions as neExceptions
from novaclient import exceptions as nvExceptions
from novaclient.exceptions import ClientException, Conflict
from osm_ro_plugin.vimconn import (
    VimConnConnectionException,
    VimConnException,
    VimConnNotFoundException,
    VimConnUnexpectedResponse,
)
from osm_rovim_openstack.vimconn_openstack import vimconnector
from requests.exceptions import ConnectionError

__author__ = "Igor D.C."
__date__ = "$23-aug-2017 23:59:59$"

# Variables Used in TestNewVmInstance Class
name = "basicvm"
description = "my firewall"
start = True
image_id = "408b73-e9cc-5a6a-t270-82cc4811bd4a"
flavor_id = "208b73-e9cc-5a6a-t270-82cc4811bd4a"
affinity_group_list = []
net_list = []
cloud_config = {}
disk_list = []
disk_list2 = [
    {"size": 10, "image_id": image_id},
    {"size": 20},
]
availability_zone_index = 0
availability_zone_list = ["nova"]
security_group_name = None
floating_network_vim_id = "108b73-e9cc-5a6a-t270-82cc4811bd4a"
net_id = "83372685-f67f-49fd-8722-eabb7692fc22"
net2_id = "46472685-f67f-49fd-8722-eabb7692fc22"
mac_address = "00:00:5e:00:53:af"
port_id = "03372685-f67f-49fd-8722-eabb7692fc22"
time_return_value = 156570000
port2_id = "17472685-f67f-49fd-8722-eabb7692fc22"
root_vol_id = "tc408b73-r9cc-5a6a-a270-82cc4811bd4a"
ip_addr1 = "20.3.4.5"
volume_id = "ac408b73-b9cc-4a6a-a270-82cc4811bd4a"
volume_id2 = "o4e0e83-b9uu-4akk-a234-89cc4811bd4a"
volume_id3 = "44e0e83-t9uu-4akk-a234-p9cc4811bd4a"
volume_id4 = "91bf5674-5b85-41d1-aa3b-4848e2691088"
virtual_mac_id = "64e0e83-t9uu-4akk-a234-p9cc4811bd4a"
created_items_all_true = {
    f"floating_ip:{floating_network_vim_id}": True,
    f"volume:{volume_id}": True,
    f"port:{port_id}": True,
}


# Variables used in TestNewFlavor Class
name1 = "sample-flavor"
extended = (
    {
        "cpu-quota": {"limit": 3},
        "mem-quota": {"limit": 1},
        "mempage-size": "LARGE",
        "cpu-pinning-policy": "DEDICATED",
        "mem-policy": "STRICT",
    },
)
flavor_data = {
    "name": name1,
    "ram": 3,
    "vcpus": 8,
    "disk": 50,
    "extended": extended,
}

flavor_data2 = {
    "name": name1,
    "ram": 3,
    "vcpus": 8,
    "disk": 50,
}


def check_if_assert_not_called(mocks: list):
    for mocking in mocks:
        mocking.assert_not_called()


class Volume:
    def __init__(self, s, type="__DEFAULT__", name="", id=""):
        self.status = s
        self.volume_type = type
        self.name = name
        self.id = id


class Server:
    def __init__(self, name="", status="", flavor="", id=""):
        self.id = id
        self.name = name
        self.status = status
        self.flavor = flavor


class CopyingMock(MagicMock):
    def __call__(self, *args, **kwargs):
        args = deepcopy(args)
        kwargs = deepcopy(kwargs)
        return super(CopyingMock, self).__call__(*args, **kwargs)


class TestNewVmInstance(unittest.TestCase):
    @patch("logging.getLogger", autospec=True)
    def setUp(self, mock_logger):
        # Instantiate dummy VIM connector so we can test it
        # It throws exception because of dummy parameters,
        # We are disabling the logging of exception not to print them to console.
        mock_logger = logging.getLogger()
        mock_logger.disabled = True
        self.vimconn = vimconnector(
            "123",
            "openstackvim",
            "456",
            "789",
            "http://dummy.url",
            None,
            "user",
            "pass",
        )
        self.vimconn.neutron = CopyingMock()
        self.vimconn.nova = CopyingMock()
        self.vimconn.cinder = CopyingMock()
        self.server = MagicMock(object, autospec=True)
        self.server.tenant_id = "408b73-r9cc-5a6a-a270-82cc4811bd4a"
        self.server.id = "908b73-e9cc-5a6a-t270-82cc4811bd4a"
        self.vimconn.config["security_groups"] = "default"
        self.vimconn.config["keypair"] = "my_keypair"
        self.vimconn.security_groups_id = "12345"
        self.vimconn.nova.api_version.get_string.return_value = "2.32"
        self.vimconn.logger = CopyingMock()

    @patch.object(vimconnector, "_get_ids_from_name")
    def test_prepare_port_dict_security_security_groups_exists_in_config(
        self, mock_get_ids
    ):
        """In VIM config security_groups exists, net port_security is True
        no_port_security_extension does not exist.
        """
        self.vimconn.config = {"security_groups": "example_security_group"}
        net = {"port_security": True}
        port_dict = {}
        result_dict = {"security_groups": "12345"}

        self.vimconn._prepare_port_dict_security_groups(net, port_dict)
        self.assertDictEqual(result_dict, port_dict)
        mock_get_ids.assert_not_called()

    @patch.object(vimconnector, "_get_ids_from_name")
    def test_prepare_port_dict_security_security_groups_exists_in_config_no_security_groups_id(
        self, mock_get_ids
    ):
        """In VIM config Security_groups exists, net port_security is True, vim security_groups_id does not exist,
        no_port_security_extension does not exist.
        """
        self.vimconn.config = {"security_groups": "example_security_group"}
        self.vimconn.security_groups_id = None
        net = {"port_security": True}
        port_dict = {}
        result_dict = {"security_groups": None}

        self.vimconn._prepare_port_dict_security_groups(net, port_dict)
        self.assertDictEqual(result_dict, port_dict)
        mock_get_ids.assert_called()

    @patch.object(vimconnector, "_get_ids_from_name")
    def test_prepare_port_dict_security_security_groups_exists_security_extension_true_in_config(
        self, mock_get_ids
    ):
        """In VIM config security_groups exists, net port_security is True, in VIM security_groups_id exists,
        no_port_security_extension set to True.
        """
        self.vimconn.config = {
            "security_groups": "example_security_group",
            "no_port_security_extension": True,
        }
        net = {"port_security": True}
        port_dict = {}
        result_dict = {}

        self.vimconn._prepare_port_dict_security_groups(net, port_dict)
        self.assertDictEqual(result_dict, port_dict)
        mock_get_ids.assert_not_called()

    @patch.object(vimconnector, "_get_ids_from_name")
    def test_prepare_port_dict_security_no_security_groups_in_config(
        self, mock_get_ids
    ):
        """In VIM config security_group does not exist, net port_security True, in VIM security_groups_id exists,
        no_port_security_extension does not exist."""
        self.vimconn.config = {}
        net = {"port_security": True}
        port_dict = {}
        result_dict = {}

        self.vimconn._prepare_port_dict_security_groups(net, port_dict)
        self.assertDictEqual(result_dict, port_dict)
        mock_get_ids.assert_not_called()

    @patch.object(vimconnector, "_get_ids_from_name")
    def test_prepare_port_dict_security_no_security_groups_security_extension_true_in_config(
        self, mock_get_ids
    ):
        """Security_group does not exist, net port_security is True, in VIM security_groups_id exists,
        no_port_security_extension set to True."""
        self.vimconn.config = {"no_port_security_extension": True}
        net = {"port_security": True}
        port_dict = {}
        result_dict = {}

        self.vimconn._prepare_port_dict_security_groups(net, port_dict)
        self.assertDictEqual(result_dict, port_dict)
        mock_get_ids.assert_not_called()

    @patch.object(vimconnector, "_get_ids_from_name")
    def test_prepare_port_dict_security_security_groups_exists_net_port_security_false(
        self, mock_get_ids
    ):
        """In VIM config security_group exists, net port_security False, security_groups_id exists,
        no_port_security_extension does not exist."""
        self.vimconn.config = {"security_groups": "example_security_group"}
        net = {"port_security": False}
        port_dict = {}
        result_dict = {}

        self.vimconn._prepare_port_dict_security_groups(net, port_dict)
        self.assertDictEqual(result_dict, port_dict)
        mock_get_ids.assert_not_called()

    @patch.object(vimconnector, "_get_ids_from_name")
    def test_prepare_port_dict_security_net_port_security_false_port_security_extension_true(
        self, mock_get_ids
    ):
        """In VIM config security_group exists, net port_security False, security_groups_id exists,
        no_port_security_extension set to True."""
        self.vimconn.config = {
            "security_groups": "example_security_group",
            "no_port_security_extension": True,
        }
        net = {"port_security": False}
        port_dict = {}
        result_dict = {}

        self.vimconn._prepare_port_dict_security_groups(net, port_dict)
        self.assertDictEqual(result_dict, port_dict)
        mock_get_ids.assert_not_called()

    def test_prepare_port_dict_binding_net_type_virtual(self):
        """net type is virtual."""
        net = {"type": "virtual"}
        port_dict = {}
        result_dict = {}
        self.vimconn._prepare_port_dict_binding(net, port_dict)
        self.assertDictEqual(result_dict, port_dict)

    def test_prepare_port_dict_binding_net_type_vf(self):
        """net type is VF, vim_type is not VIO."""
        net = {"type": "VF"}
        self.vimconn.vim_type = None
        port_dict = {}
        result_dict = {"binding:vnic_type": "direct"}
        self.vimconn._prepare_port_dict_binding(net, port_dict)
        self.assertDictEqual(port_dict, result_dict)

    def test_prepare_port_dict_binding_net_type_sriov_vim_type_vio(self):
        """net type is SR-IOV, vim_type is VIO."""
        net = {"type": "SR-IOV"}
        self.vimconn.vim_type = "VIO"
        port_dict = {}
        result_dict = {
            "binding:vnic_type": "direct",
            "port_security_enabled": False,
            "provider_security_groups": [],
            "security_groups": [],
        }
        self.vimconn._prepare_port_dict_binding(net, port_dict)
        self.assertDictEqual(port_dict, result_dict)

    def test_prepare_port_dict_binding_net_type_passthrough(self):
        """net type is pci-passthrough."""
        net = {"type": "PCI-PASSTHROUGH"}
        port_dict = {}
        result_dict = {
            "binding:vnic_type": "direct-physical",
        }
        self.vimconn._prepare_port_dict_binding(net, port_dict)
        self.assertDictEqual(port_dict, result_dict)

    def test_prepare_port_dict_binding_no_net_type(self):
        """net type is missing."""
        net = {}
        port_dict = {}
        with self.assertRaises(VimConnException) as err:
            self.vimconn._prepare_port_dict_binding(net, port_dict)
        self.assertEqual(str(err.exception), "Type is missing in the network details.")

    def test_set_fixed_ip(self):
        """new_port has fixed ip."""
        net = {}
        new_port = {
            "port": {
                "fixed_ips": [{"ip_address": "10.1.2.3"}, {"ip_address": "20.1.2.3"}]
            }
        }
        result = {"ip": "10.1.2.3"}
        self.vimconn._set_fixed_ip(new_port, net)
        self.assertDictEqual(net, result)

    def test_set_fixed_ip_no_fixed_ip(self):
        """new_port does not have fixed ip."""
        net = {}
        new_port = {"port": {}}
        result = {"ip": None}
        self.vimconn._set_fixed_ip(new_port, net)
        self.assertDictEqual(net, result)

    def test_set_fixed_ip_raise_exception(self):
        """new_port does not have port details."""
        net = {}
        new_port = {}
        with self.assertRaises(Exception) as err:
            self.vimconn._set_fixed_ip(new_port, net)
        self.assertEqual(type(err.exception), KeyError)

    def test_prepare_port_dict_mac_ip_addr(self):
        """mac address and ip address exist."""
        net = {
            "mac_address": mac_address,
            "ip_address": "10.0.1.5",
        }
        port_dict = {}
        result_dict = {
            "mac_address": mac_address,
            "fixed_ips": [{"ip_address": "10.0.1.5"}],
        }
        self.vimconn._prepare_port_dict_mac_ip_addr(net, port_dict)
        self.assertDictEqual(port_dict, result_dict)

    def test_prepare_port_dict_mac_ip_addr_empty_net(self):
        """mac address and ip address does not exist."""
        net = {}
        port_dict = {}
        result_dict = {}
        self.vimconn._prepare_port_dict_mac_ip_addr(net, port_dict)
        self.assertDictEqual(port_dict, result_dict)

    def test_prepare_port_dict_mac_ip_addr_dual(self):
        """mac address, ipv4 and ipv6 addresses exist."""
        net = {
            "mac_address": mac_address,
            "ip_address": ["10.0.1.5", "2345:0425:2CA1:0000:0000:0567:5673:23b5"],
        }
        port_dict = {}
        result_dict = {
            "mac_address": mac_address,
            "fixed_ips": [
                {"ip_address": "10.0.1.5"},
                {"ip_address": "2345:0425:2CA1:0000:0000:0567:5673:23b5"},
            ],
        }
        self.vimconn._prepare_port_dict_mac_ip_addr(net, port_dict)
        self.assertDictEqual(port_dict, result_dict)

    def test_prepare_port_dict_mac_ip_addr_dual_ip_addr_is_not_list(self):
        """mac address, ipv4 and ipv6 addresses exist."""
        net = {
            "mac_address": mac_address,
            "ip_address": "10.0.1.5",
        }
        port_dict = {}
        result_dict = {
            "mac_address": mac_address,
            "fixed_ips": [
                {"ip_address": "10.0.1.5"},
            ],
        }
        self.vimconn._prepare_port_dict_mac_ip_addr(net, port_dict)
        self.assertDictEqual(port_dict, result_dict)

    def test_prepare_port_dict_mac_ip_addr_dual_net_without_ip_addr(self):
        """mac address, ipv4 and ipv6 addresses exist."""
        net = {
            "mac_address": mac_address,
            "ip_address": [],
        }
        port_dict = {}
        result_dict = {
            "mac_address": mac_address,
        }
        self.vimconn._prepare_port_dict_mac_ip_addr(net, port_dict)
        self.assertDictEqual(port_dict, result_dict)

    def test_prepare_port_dict_mac_ip_addr_dual_net_without_mac_addr(self):
        """mac address, ipv4 and ipv6 addresses exist."""
        net = {
            "ip_address": ["10.0.1.5", "2345:0425:2CA1:0000:0000:0567:5673:23b5"],
        }
        port_dict = {}
        result_dict = {
            "fixed_ips": [
                {"ip_address": "10.0.1.5"},
                {"ip_address": "2345:0425:2CA1:0000:0000:0567:5673:23b5"},
            ],
        }
        self.vimconn._prepare_port_dict_mac_ip_addr(net, port_dict)
        self.assertDictEqual(port_dict, result_dict)

    def test_create_new_port(self):
        """new port has id and mac address."""
        new_port = {
            "port": {
                "id": port_id,
                "mac_address": mac_address,
            },
        }
        self.vimconn.neutron.create_port.return_value = new_port
        net, port_dict, created_items = {}, {}, {}
        expected_result = new_port
        expected_net = {
            "mac_address": mac_address,
            "vim_id": port_id,
        }
        expected_created_items = {f"port:{port_id}": True}
        result = self.vimconn._create_new_port(port_dict, created_items, net)
        self.assertDictEqual(result, expected_result)
        self.assertEqual(net, expected_net)
        self.assertEqual(created_items, expected_created_items)
        self.vimconn.neutron.create_port.assert_called_once_with({"port": port_dict})

    def test_create_new_port_without_mac_or_id(self):
        """new port does not have mac address or ID."""
        new_port = {}
        self.vimconn.neutron.create_port.return_value = new_port
        net, port_dict, created_items = {}, {}, {}
        with self.assertRaises(KeyError):
            self.vimconn._create_new_port(port_dict, created_items, net)
        self.vimconn.neutron.create_port.assert_called_once_with({"port": port_dict})

    def test_create_new_port_neutron_create_port_raises_exception(self):
        """Neutron create port raises exception."""
        self.vimconn.neutron.create_port.side_effect = VimConnException(
            "New port is not created."
        )
        net, port_dict, created_items = {}, {}, {}
        with self.assertRaises(VimConnException):
            self.vimconn._create_new_port(port_dict, created_items, net)
        self.vimconn.neutron.create_port.assert_called_once_with({"port": port_dict})

    @patch.object(vimconnector, "_prepare_port_dict_security_groups")
    @patch.object(vimconnector, "_prepare_port_dict_binding")
    @patch.object(vimconnector, "_prepare_port_dict_mac_ip_addr")
    @patch.object(vimconnector, "_create_new_port")
    @patch.object(vimconnector, "_set_fixed_ip")
    def test_create_port(
        self,
        mock_set_fixed_ip,
        mock_create_new_port,
        mock_prepare_port_dict_mac_ip_addr,
        mock_prepare_port_dict_binding,
        mock_prepare_port_dict_security_groups,
    ):
        """Net has name, type, net-id."""

        net = {
            "net_id": net_id,
            "name": "management",
            "type": "virtual",
        }
        created_items = {}
        new_port = {
            "port": {
                "id": net_id,
                "mac_address": mac_address,
                "name": "management",
                "fixed_ips": [{"ip_address": ip_addr1}],
            },
        }
        mock_create_new_port.return_value = new_port
        expected_port = {
            "port-id": net_id,
            "tag": "management",
        }
        port_dict = {
            "network_id": net_id,
            "name": "management",
            "admin_state_up": True,
        }
        security_group_name = None

        new_port_result, port_result = self.vimconn._create_port(
            net, name, created_items
        )

        self.assertDictEqual(new_port_result, new_port)
        self.assertDictEqual(port_result, expected_port)

        mock_prepare_port_dict_security_groups.assert_called_once_with(
            net, port_dict, security_group_name
        )
        mock_prepare_port_dict_binding.assert_called_once_with(net, port_dict)
        mock_prepare_port_dict_mac_ip_addr.assert_called_once_with(net, port_dict)
        mock_create_new_port.assert_called_once_with(port_dict, created_items, net)
        mock_set_fixed_ip.assert_called_once_with(new_port, net)

    @patch.object(vimconnector, "_prepare_port_dict_security_groups")
    @patch.object(vimconnector, "_prepare_port_dict_binding")
    @patch.object(vimconnector, "_prepare_port_dict_mac_ip_addr")
    @patch.object(vimconnector, "_create_new_port")
    @patch.object(vimconnector, "_set_fixed_ip")
    def test_create_port_no_port_name(
        self,
        mock_set_fixed_ip,
        mock_create_new_port,
        mock_prepare_port_dict_mac_ip_addr,
        mock_prepare_port_dict_binding,
        mock_prepare_port_dict_security_groups,
    ):
        """Net has no name."""
        net = {
            "net_id": net_id,
            "type": "virtual",
        }
        created_items = {}
        new_port = {
            "port": {
                "id": net_id,
                "mac_address": mac_address,
                "name": name,
                "fixed_ips": [{"ip_address": ip_addr1}],
            },
        }
        mock_create_new_port.return_value = new_port
        expected_port = {
            "port-id": net_id,
            "tag": name,
        }
        port_dict = {
            "network_id": net_id,
            "admin_state_up": True,
            "name": name,
        }
        security_group_name = None

        new_port_result, port_result = self.vimconn._create_port(
            net, name, created_items
        )

        self.assertDictEqual(new_port_result, new_port)
        self.assertDictEqual(port_result, expected_port)

        mock_prepare_port_dict_security_groups.assert_called_once_with(
            net, port_dict, security_group_name
        )
        mock_prepare_port_dict_binding.assert_called_once_with(net, port_dict)
        mock_prepare_port_dict_mac_ip_addr.assert_called_once_with(net, port_dict)
        mock_create_new_port.assert_called_once_with(port_dict, created_items, net)
        mock_set_fixed_ip.assert_called_once_with(new_port, net)

    @patch.object(vimconnector, "_prepare_port_dict_security_groups")
    @patch.object(vimconnector, "_prepare_port_dict_binding")
    @patch.object(vimconnector, "_prepare_port_dict_mac_ip_addr")
    @patch.object(vimconnector, "_create_new_port")
    @patch.object(vimconnector, "_set_fixed_ip")
    def test_create_port_nova_api_version_smaller_than_232(
        self,
        mock_set_fixed_ip,
        mock_create_new_port,
        mock_prepare_port_dict_mac_ip_addr,
        mock_prepare_port_dict_binding,
        mock_prepare_port_dict_security_groups,
    ):
        """Nova api version is smaller than 2.32."""
        self.vimconn.nova.api_version.get_string.return_value = "2.30"
        net = {
            "net_id": net_id,
            "type": "virtual",
        }
        created_items = {}
        new_port = {
            "port": {
                "id": net_id,
                "mac_address": mac_address,
                "name": name,
                "fixed_ips": [{"ip_address": ip_addr1}],
            },
        }
        mock_create_new_port.return_value = new_port
        expected_port = {
            "port-id": net_id,
        }
        port_dict = {
            "network_id": net_id,
            "admin_state_up": True,
            "name": name,
        }
        security_group_name = None

        new_port_result, port_result = self.vimconn._create_port(
            net, name, created_items
        )

        self.assertDictEqual(new_port_result, new_port)
        self.assertDictEqual(port_result, expected_port)

        mock_prepare_port_dict_security_groups.assert_called_once_with(
            net, port_dict, security_group_name
        )
        mock_prepare_port_dict_binding.assert_called_once_with(net, port_dict)
        mock_prepare_port_dict_mac_ip_addr.assert_called_once_with(net, port_dict)
        mock_create_new_port.assert_called_once_with(port_dict, created_items, net)
        mock_set_fixed_ip.assert_called_once_with(new_port, net)

    @patch.object(vimconnector, "_prepare_port_dict_security_groups")
    @patch.object(vimconnector, "_prepare_port_dict_binding")
    @patch.object(vimconnector, "_prepare_port_dict_mac_ip_addr")
    @patch.object(vimconnector, "_create_new_port")
    @patch.object(vimconnector, "_set_fixed_ip")
    def test_create_port_create_new_port_raise_exception(
        self,
        mock_set_fixed_ip,
        mock_create_new_port,
        mock_prepare_port_dict_mac_ip_addr,
        mock_prepare_port_dict_binding,
        mock_prepare_port_dict_security_groups,
    ):
        """_create_new_port method raises exception."""
        net = {
            "net_id": net_id,
            "type": "virtual",
        }
        created_items = {}
        mock_create_new_port.side_effect = Exception
        port_dict = {
            "network_id": net_id,
            "admin_state_up": True,
            "name": name,
        }
        security_group_name = None

        with self.assertRaises(Exception):
            self.vimconn._create_port(net, name, created_items)

        mock_prepare_port_dict_security_groups.assert_called_once_with(
            net, port_dict, security_group_name
        )
        mock_prepare_port_dict_binding.assert_called_once_with(net, port_dict)
        mock_prepare_port_dict_mac_ip_addr.assert_called_once_with(net, port_dict)
        mock_create_new_port.assert_called_once_with(port_dict, created_items, net)
        mock_set_fixed_ip.assert_not_called()

    @patch.object(vimconnector, "_prepare_port_dict_security_groups")
    @patch.object(vimconnector, "_prepare_port_dict_binding")
    @patch.object(vimconnector, "_prepare_port_dict_mac_ip_addr")
    @patch.object(vimconnector, "_create_new_port")
    @patch.object(vimconnector, "_set_fixed_ip")
    def test_create_port_create_sec_groups_raises_exception(
        self,
        mock_set_fixed_ip,
        mock_create_new_port,
        mock_prepare_port_dict_mac_ip_addr,
        mock_prepare_port_dict_binding,
        mock_prepare_port_dict_security_groups,
    ):
        """_prepare_port_dict_security_groups method raises exception."""
        net = {
            "net_id": net_id,
            "type": "virtual",
        }
        created_items = {}
        mock_prepare_port_dict_security_groups.side_effect = Exception
        port_dict = {
            "network_id": net_id,
            "admin_state_up": True,
            "name": name,
        }
        security_group_name = None

        with self.assertRaises(Exception):
            self.vimconn._create_port(net, name, created_items)

        mock_prepare_port_dict_security_groups.assert_called_once_with(
            net, port_dict, security_group_name
        )

        mock_prepare_port_dict_binding.assert_not_called()
        mock_prepare_port_dict_mac_ip_addr.assert_not_called()
        mock_create_new_port.assert_not_called()
        mock_set_fixed_ip.assert_not_called()

    @patch.object(vimconnector, "_prepare_port_dict_security_groups")
    @patch.object(vimconnector, "_prepare_port_dict_binding")
    @patch.object(vimconnector, "_prepare_port_dict_mac_ip_addr")
    @patch.object(vimconnector, "_create_new_port")
    @patch.object(vimconnector, "_set_fixed_ip")
    def test_create_port_create_port_dict_binding_raise_exception(
        self,
        mock_set_fixed_ip,
        mock_create_new_port,
        mock_prepare_port_dict_mac_ip_addr,
        mock_prepare_port_dict_binding,
        mock_prepare_port_dict_security_groups,
    ):
        """_prepare_port_dict_binding method raises exception."""

        net = {
            "net_id": net_id,
            "type": "virtual",
        }
        created_items = {}
        mock_prepare_port_dict_binding.side_effect = Exception
        port_dict = {
            "network_id": net_id,
            "admin_state_up": True,
            "name": name,
        }
        security_group_name = None

        with self.assertRaises(Exception):
            self.vimconn._create_port(net, name, created_items)

        mock_prepare_port_dict_security_groups.assert_called_once_with(
            net, port_dict, security_group_name
        )

        mock_prepare_port_dict_binding.assert_called_once_with(net, port_dict)

        mock_prepare_port_dict_mac_ip_addr.assert_not_called()
        mock_create_new_port.assert_not_called()
        mock_set_fixed_ip.assert_not_called()

    @patch.object(vimconnector, "_prepare_port_dict_security_groups")
    @patch.object(vimconnector, "_prepare_port_dict_binding")
    @patch.object(vimconnector, "_prepare_port_dict_mac_ip_addr")
    @patch.object(vimconnector, "_create_new_port")
    @patch.object(vimconnector, "_set_fixed_ip")
    def test_create_port_create_port_mac_ip_addr_raise_exception(
        self,
        mock_set_fixed_ip,
        mock_create_new_port,
        mock_prepare_port_dict_mac_ip_addr,
        mock_prepare_port_dict_binding,
        mock_prepare_port_dict_security_groups,
    ):
        """prepare_port_dict_mac_ip_addr method raises exception."""
        net = {
            "net_id": net_id,
            "type": "virtual",
        }
        created_items = {}
        mock_prepare_port_dict_mac_ip_addr.side_effect = Exception
        port_dict = {
            "network_id": net_id,
            "admin_state_up": True,
            "name": name,
        }
        security_group_name = None

        with self.assertRaises(Exception):
            self.vimconn._create_port(net, name, created_items)

        mock_prepare_port_dict_security_groups.assert_called_once_with(
            net, port_dict, security_group_name
        )
        mock_prepare_port_dict_binding.assert_called_once_with(net, port_dict)
        mock_prepare_port_dict_mac_ip_addr.assert_called_once_with(net, port_dict)

        mock_create_new_port.assert_not_called()
        mock_set_fixed_ip.assert_not_called()

    @patch.object(vimconnector, "_prepare_port_dict_security_groups")
    @patch.object(vimconnector, "_prepare_port_dict_binding")
    @patch.object(vimconnector, "_prepare_port_dict_mac_ip_addr")
    @patch.object(vimconnector, "_create_new_port")
    @patch.object(vimconnector, "_set_fixed_ip")
    def test_create_port_create_port_set_fixed_ip_raise_exception(
        self,
        mock_set_fixed_ip,
        mock_create_new_port,
        mock_prepare_port_dict_mac_ip_addr,
        mock_prepare_port_dict_binding,
        mock_prepare_port_dict_security_groups,
    ):
        """_set_fixed_ip method raises exception."""
        net = {
            "net_id": net_id,
            "type": "virtual",
        }
        created_items = {}
        mock_set_fixed_ip.side_effect = VimConnException(
            "Port detail is missing in new_port."
        )
        port_dict = {
            "network_id": net_id,
            "admin_state_up": True,
            "name": name,
        }
        new_port = {
            "port": {
                "id": net_id,
                "mac_address": mac_address,
                "name": name,
                "fixed_ips": [{"ip_address": ip_addr1}],
            },
        }
        security_group_name = None
        mock_create_new_port.return_value = new_port

        with self.assertRaises(VimConnException):
            self.vimconn._create_port(net, name, created_items)

        mock_prepare_port_dict_security_groups.assert_called_once_with(
            net, port_dict, security_group_name
        )
        mock_prepare_port_dict_binding.assert_called_once_with(net, port_dict)
        mock_prepare_port_dict_mac_ip_addr.assert_called_once_with(net, port_dict)
        mock_create_new_port.assert_called_once_with(port_dict, created_items, net)
        mock_set_fixed_ip.assert_called_once_with(new_port, net)

    @patch.object(vimconnector, "_reload_connection")
    @patch.object(vimconnector, "_create_port")
    def test_prepare_network_for_vm_instance_no_net_id(
        self, mock_create_port, mock_reload_connection
    ):
        """Nets do not have net_id"""
        mock_reload_connection.side_effect = None
        created_items = {}
        net_list = [
            {
                "use": "mgmt",
                "port_security": False,
                "exit_on_floating_ip_error": False,
                "port_security_disable_strategy": "full",
            },
            {
                "port_security": True,
                "exit_on_floating_ip_error": False,
                "floating_ip": True,
            },
        ]
        net_list_vim = []
        external_network, no_secured_ports = [], []
        expected_external_network, expected_no_secured_ports = [], []
        expected_net_list_vim = []

        self.vimconn._prepare_network_for_vminstance(
            name,
            net_list,
            created_items,
            net_list_vim,
            external_network,
            no_secured_ports,
        )
        self.assertEqual(expected_net_list_vim, net_list_vim)
        self.assertEqual(external_network, expected_external_network)
        self.assertEqual(expected_no_secured_ports, no_secured_ports)

        mock_create_port.assert_not_called()

    @patch.object(vimconnector, "_reload_connection")
    @patch.object(vimconnector, "_create_port")
    def test_prepare_network_for_vm_instance_empty_net_list(
        self, mock_create_port, mock_reload_connection
    ):
        """Net list is empty."""
        mock_reload_connection.side_effect = None
        created_items = {}
        net_list_vim = []
        external_network, no_secured_ports = [], []
        expected_external_network, expected_no_secured_ports = [], []
        expected_net_list_vim = []

        self.vimconn._prepare_network_for_vminstance(
            name,
            net_list,
            created_items,
            net_list_vim,
            external_network,
            no_secured_ports,
        )
        self.assertEqual(expected_net_list_vim, net_list_vim)
        self.assertEqual(external_network, expected_external_network)
        self.assertEqual(expected_no_secured_ports, no_secured_ports)

        mock_create_port.assert_not_called()

    @patch.object(vimconnector, "_reload_connection")
    @patch.object(vimconnector, "_create_port")
    def test_prepare_network_for_vm_instance_use_floating_ip_false_mgmt_net(
        self, mock_create_port, mock_reload_connection
    ):
        """Nets have net-id, floating_ip False, mgmt network."""
        mock_reload_connection.side_effect = None
        created_items = {}
        net_list = [
            {
                "net_id": net2_id,
                "floating_ip": False,
                "use": "mgmt",
            }
        ]
        net_list_vim = []
        mock_create_port.side_effect = [
            (
                {
                    "port": {
                        "id": port2_id,
                        "mac_address": mac_address,
                        "name": name,
                    },
                },
                {"port-dict": port2_id},
            ),
        ]
        external_network, no_secured_ports = [], []
        expected_external_network, expected_no_secured_ports = [], []
        expected_net_list_vim = [{"port-dict": port2_id}]
        self.vimconn._prepare_network_for_vminstance(
            name,
            net_list,
            created_items,
            net_list_vim,
            external_network,
            no_secured_ports,
        )
        self.assertEqual(expected_net_list_vim, net_list_vim)
        self.assertEqual(external_network, expected_external_network)
        self.assertEqual(expected_no_secured_ports, no_secured_ports)

        security_group_name = None
        mock_create_port.assert_called_once_with(
            {
                "net_id": net2_id,
                "floating_ip": False,
                "use": "mgmt",
            },
            name,
            created_items,
            security_group_name,
        )

    @patch.object(vimconnector, "_reload_connection")
    def test_prepare_network_for_vm_instance_mgmt_net_net_port_security_and_floating_ip_true(
        self, mock_reload_connection
    ):
        """Nets have net-id, use_floating_ip False in VIM config, mgmt network, net floating_ip is True."""
        self.vimconn.config["use_floating_ip"] = False
        mock_create_port = CopyingMock()
        mock_reload_connection.side_effect = None
        created_items = {}
        net_list = [
            {
                "net_id": net2_id,
                "floating_ip": True,
                "use": "mgmt",
            }
        ]
        net_list_vim = []
        mock_create_port.side_effect = [
            (
                {
                    "port": {
                        "id": port2_id,
                        "mac_address": mac_address,
                        "name": name,
                    },
                },
                {"port-dict": port2_id},
            ),
        ]
        external_network, no_secured_ports = [], []
        expected_external_network = [
            {
                "net_id": net2_id,
                "floating_ip": True,
                "use": "mgmt",
                "exit_on_floating_ip_error": True,
            },
        ]
        expected_no_secured_ports = []
        expected_net_list_vim = [{"port-dict": port2_id}]
        with patch.object(vimconnector, "_create_port", mock_create_port):
            self.vimconn._prepare_network_for_vminstance(
                name,
                net_list,
                created_items,
                net_list_vim,
                external_network,
                no_secured_ports,
            )
        self.assertEqual(expected_net_list_vim, net_list_vim)
        self.assertEqual(external_network, expected_external_network)
        self.assertEqual(expected_no_secured_ports, no_secured_ports)

        security_group_name = None
        mock_create_port.assert_called_once_with(
            {
                "net_id": net2_id,
                "floating_ip": True,
                "use": "mgmt",
            },
            name,
            created_items,
            security_group_name,
        )

    @patch.object(vimconnector, "_reload_connection")
    def test_prepare_network_for_vm_instance_use_floating_ip_true_mgmt_net_port_security_false(
        self, mock_reload_connection
    ):
        """Nets have net-id, use_floating_ip is True in VIM config, mgmt network, net port security is False."""
        mock_create_port = CopyingMock()
        self.vimconn.config["use_floating_ip"] = True
        self.vimconn.config["no_port_security_extension"] = False
        mock_reload_connection.side_effect = None
        created_items = {}

        net_list = [
            {
                "net_id": net2_id,
                "use": "mgmt",
                "port_security": False,
                "exit_on_floating_ip_error": False,
                "port_security_disable_strategy": "full",
            }
        ]
        net_list_vim = []
        mock_create_port.side_effect = [
            (
                {
                    "port": {
                        "id": port2_id,
                        "mac_address": mac_address,
                        "name": name,
                    },
                },
                {"port-dict": port2_id},
            ),
        ]
        external_network, no_secured_ports = [], []
        expected_external_network = [
            {
                "net_id": net2_id,
                "use": "mgmt",
                "port_security": False,
                "exit_on_floating_ip_error": False,
                "port_security_disable_strategy": "full",
                "floating_ip": True,
            },
        ]
        expected_no_secured_ports = [(port2_id, "full")]
        expected_net_list_vim = [{"port-dict": port2_id}]
        with patch.object(vimconnector, "_create_port", mock_create_port):
            self.vimconn._prepare_network_for_vminstance(
                name,
                net_list,
                created_items,
                net_list_vim,
                external_network,
                no_secured_ports,
            )

        security_group_name = None
        mock_create_port.assert_called_once_with(
            {
                "net_id": net2_id,
                "use": "mgmt",
                "port_security": False,
                "exit_on_floating_ip_error": False,
                "port_security_disable_strategy": "full",
            },
            name,
            created_items,
            security_group_name,
        )
        self.assertEqual(expected_net_list_vim, net_list_vim)
        self.assertEqual(external_network, expected_external_network)
        self.assertEqual(expected_no_secured_ports, no_secured_ports)

    @patch.object(vimconnector, "_reload_connection")
    def test_prepare_network_for_vm_instance_use_fip_true_non_mgmt_net_port_security_false(
        self, mock_reload_connection
    ):
        """Nets have net-id, use_floating_ip True in VIM config, non-mgmt network, port security is False."""
        mock_create_port = CopyingMock()
        self.vimconn.config["use_floating_ip"] = True
        self.vimconn.config["no_port_security_extension"] = False
        mock_reload_connection.side_effect = None
        created_items = {}

        net_list = [
            {
                "net_id": net2_id,
                "use": "other",
                "port_security": False,
                "port_security_disable_strategy": "full",
            }
        ]
        net_list_vim = []
        mock_create_port.side_effect = [
            (
                {
                    "port": {
                        "id": port2_id,
                        "mac_address": mac_address,
                        "name": name,
                    },
                },
                {"port-dict": port2_id},
            ),
        ]
        external_network, no_secured_ports = [], []
        expected_external_network = []
        expected_no_secured_ports = [(port2_id, "full")]
        expected_net_list_vim = [{"port-dict": port2_id}]
        with patch.object(vimconnector, "_create_port", mock_create_port):
            self.vimconn._prepare_network_for_vminstance(
                name,
                net_list,
                created_items,
                net_list_vim,
                external_network,
                no_secured_ports,
            )

        security_group_name = None
        mock_create_port.assert_called_once_with(
            {
                "net_id": net2_id,
                "use": "other",
                "port_security": False,
                "port_security_disable_strategy": "full",
            },
            name,
            created_items,
            security_group_name,
        )
        self.assertEqual(expected_net_list_vim, net_list_vim)
        self.assertEqual(external_network, expected_external_network)
        self.assertEqual(expected_no_secured_ports, no_secured_ports)

    @patch.object(vimconnector, "_reload_connection")
    def test_prepare_network_for_vm_instance_use_fip_true_non_mgmt_net_port_security_true(
        self, mock_reload_connection
    ):
        """Nets have net-id, use_floating_ip is True in VIM config, non-mgmt network, net port security is True."""
        mock_create_port = CopyingMock()
        self.vimconn.config["use_floating_ip"] = True
        self.vimconn.config["no_port_security_extension"] = True
        mock_reload_connection.side_effect = None
        created_items = {}

        net_list = [
            {
                "net_id": net2_id,
                "use": "other",
                "port_security": True,
                "port_security_disable_strategy": "full",
            }
        ]
        net_list_vim = []
        mock_create_port.side_effect = [
            (
                {
                    "port": {
                        "id": port2_id,
                        "mac_address": mac_address,
                        "name": name,
                    },
                },
                {"port-dict": port2_id},
            ),
        ]
        external_network, no_secured_ports = [], []
        expected_external_network = []
        expected_no_secured_ports = []
        expected_net_list_vim = [{"port-dict": port2_id}]
        with patch.object(vimconnector, "_create_port", mock_create_port):
            self.vimconn._prepare_network_for_vminstance(
                name,
                net_list,
                created_items,
                net_list_vim,
                external_network,
                no_secured_ports,
            )

        security_group_name = None
        mock_create_port.assert_called_once_with(
            {
                "net_id": net2_id,
                "use": "other",
                "port_security": True,
                "port_security_disable_strategy": "full",
            },
            name,
            created_items,
            security_group_name,
        )
        self.assertEqual(expected_net_list_vim, net_list_vim)
        self.assertEqual(external_network, expected_external_network)
        self.assertEqual(expected_no_secured_ports, no_secured_ports)

    @patch.object(vimconnector, "_reload_connection")
    def test_prepare_network_for_vm_instance_create_port_raise_exception(
        self, mock_reload_connection
    ):
        """_create_port method raise exception."""
        mock_create_port = CopyingMock()
        self.vimconn.config["use_floating_ip"] = True
        self.vimconn.config["no_port_security_extension"] = True
        mock_reload_connection.side_effect = None
        created_items = {}

        net_list = [
            {
                "net_id": net2_id,
                "use": "other",
                "port_security": True,
                "port_security_disable_strategy": "full",
            }
        ]
        net_list_vim = []
        mock_create_port.side_effect = KeyError
        external_network, no_secured_ports = [], []
        expected_external_network = []
        expected_no_secured_ports = []
        expected_net_list_vim = []
        with patch.object(vimconnector, "_create_port", mock_create_port):
            with self.assertRaises(Exception) as err:
                self.vimconn._prepare_network_for_vminstance(
                    name,
                    net_list,
                    created_items,
                    net_list_vim,
                    external_network,
                    no_secured_ports,
                )

        self.assertEqual(type(err.exception), KeyError)

        security_group_name = None
        mock_create_port.assert_called_once_with(
            {
                "net_id": net2_id,
                "use": "other",
                "port_security": True,
                "port_security_disable_strategy": "full",
            },
            name,
            created_items,
            security_group_name,
        )
        self.assertEqual(expected_net_list_vim, net_list_vim)
        self.assertEqual(external_network, expected_external_network)
        self.assertEqual(expected_no_secured_ports, no_secured_ports)

    @patch.object(vimconnector, "_reload_connection")
    def test_prepare_network_for_vm_instance_reload_connection_raise_exception(
        self, mock_reload_connection
    ):
        """_reload_connection method raises exception."""
        mock_create_port = CopyingMock()
        mock_reload_connection.side_effect = VimConnConnectionException(
            "Connection failed."
        )
        self.vimconn.config["use_floating_ip"] = True
        self.vimconn.config["no_port_security_extension"] = True
        created_items = {}

        net_list = [
            {
                "net_id": net2_id,
                "use": "other",
                "port_security": True,
                "port_security_disable_strategy": "full",
            }
        ]
        net_list_vim = []
        mock_create_port.side_effect = None
        external_network, no_secured_ports = [], []
        expected_external_network = []
        expected_no_secured_ports = []
        expected_net_list_vim = []
        with patch.object(vimconnector, "_create_port", mock_create_port):
            with self.assertRaises(Exception) as err:
                self.vimconn._prepare_network_for_vminstance(
                    name,
                    net_list,
                    created_items,
                    net_list_vim,
                    external_network,
                    no_secured_ports,
                )

        self.assertEqual(type(err.exception), VimConnConnectionException)
        self.assertEqual(str(err.exception), "Connection failed.")
        mock_reload_connection.assert_called_once()
        mock_create_port.assert_not_called()
        self.assertEqual(expected_net_list_vim, net_list_vim)
        self.assertEqual(external_network, expected_external_network)
        self.assertEqual(expected_no_secured_ports, no_secured_ports)

    def test_prepare_persistent_root_volumes_vim_using_volume_id(self):
        """Existing persistent root volume with vim_volume_id."""
        storage_av_zone = ["nova"]
        base_disk_index = ord("a")
        disk = {"vim_volume_id": volume_id}
        block_device_mapping = {}
        existing_vim_volumes = []
        created_items = {}
        expected_boot_vol_id = None
        expected_block_device_mapping = {"vda": volume_id}
        expected_existing_vim_volumes = [{"id": volume_id}]
        boot_volume_id = self.vimconn._prepare_persistent_root_volumes(
            name,
            storage_av_zone,
            disk,
            base_disk_index,
            block_device_mapping,
            existing_vim_volumes,
            created_items,
        )
        self.assertEqual(boot_volume_id, expected_boot_vol_id)
        self.assertDictEqual(block_device_mapping, expected_block_device_mapping)
        self.assertEqual(existing_vim_volumes, expected_existing_vim_volumes)
        self.vimconn.cinder.volumes.create.assert_not_called()

    @patch.object(vimconnector, "update_block_device_mapping")
    def test__prepare_shared_volumes_vim_using_volume_id(
        self, mock_update_block_device_mapping
    ):
        """Existing persistent non root volume with vim_volume_id.
        class Volume:
            def __init__(self, s, type="__DEFAULT__", name="", id=""):
                self.status = s
                self.volume_type = type
                self.name = name
                self.id = id
        volumes = {"shared-volume": volume_id4}

        The device mappeing BEFORE is: {}
        The device mappeing AFTER is: {'vdb': '8ca50cc6-a779-4513-a1f3-900b8b3987d2'}
        """
        base_disk_index = ord("b")
        disk = {"name": "shared-volume"}
        block_device_mapping = {}
        existing_vim_volumes = []
        created_items = {}
        expected_block_device_mapping = {}
        self.vimconn.cinder.volumes.list.return_value = [
            Volume("available", "multiattach", "shared-volume", volume_id4)
        ]
        self.vimconn.cinder.volumes.get.return_value.id = volume_id4
        self.vimconn.cinder.volumes.get.return_value.status = "available"
        self.vimconn._prepare_shared_volumes(
            name,
            disk,
            base_disk_index,
            block_device_mapping,
            existing_vim_volumes,
            created_items,
        )
        self.vimconn.cinder.volumes.get.assert_called_with(volume_id4)
        self.assertDictEqual(block_device_mapping, expected_block_device_mapping)

    @patch.object(vimconnector, "update_block_device_mapping")
    def test_prepare_persistent_non_root_volumes_vim_using_volume_id(
        self, mock_update_block_device_mapping
    ):
        """Existing persistent non root volume with vim_volume_id."""
        storage_av_zone = ["nova"]
        base_disk_index = ord("b")
        disk = {"vim_volume_id": volume_id}
        block_device_mapping = {}
        existing_vim_volumes = []
        created_items = {}
        expected_block_device_mapping = {"vdb": volume_id}
        expected_existing_vim_volumes = [{"id": volume_id}]
        self.vimconn._prepare_non_root_persistent_volumes(
            name,
            disk,
            storage_av_zone,
            block_device_mapping,
            base_disk_index,
            existing_vim_volumes,
            created_items,
        )
        self.assertDictEqual(block_device_mapping, expected_block_device_mapping)
        self.assertEqual(existing_vim_volumes, expected_existing_vim_volumes)
        self.vimconn.cinder.volumes.create.assert_not_called()
        mock_update_block_device_mapping.assert_not_called()

    @patch.object(vimconnector, "update_block_device_mapping")
    def test_prepare_persistent_root_volumes_using_vim_id(
        self, mock_update_block_device_mapping
    ):
        """Existing persistent root volume with vim_id."""
        storage_av_zone = ["nova"]
        base_disk_index = ord("a")
        disk = {"vim_id": volume_id}
        block_device_mapping = {}
        existing_vim_volumes = []
        created_items = {}
        expected_boot_vol_id = None
        expected_block_device_mapping = {"vda": volume_id}
        expected_existing_vim_volumes = [{"id": volume_id}]
        boot_volume_id = self.vimconn._prepare_persistent_root_volumes(
            name,
            storage_av_zone,
            disk,
            base_disk_index,
            block_device_mapping,
            existing_vim_volumes,
            created_items,
        )
        self.assertEqual(boot_volume_id, expected_boot_vol_id)
        self.assertDictEqual(block_device_mapping, expected_block_device_mapping)
        self.assertEqual(existing_vim_volumes, expected_existing_vim_volumes)
        self.vimconn.cinder.volumes.create.assert_not_called()
        mock_update_block_device_mapping.assert_not_called()

    @patch.object(vimconnector, "update_block_device_mapping")
    def test_prepare_persistent_non_root_volumes_using_vim_id(
        self, mock_update_block_device_mapping
    ):
        """Existing persistent root volume with vim_id."""
        storage_av_zone = ["nova"]
        base_disk_index = ord("b")
        disk = {"vim_id": volume_id}
        block_device_mapping = {}
        existing_vim_volumes = []
        created_items = {}

        expected_block_device_mapping = {"vdb": volume_id}
        expected_existing_vim_volumes = [{"id": volume_id}]
        self.vimconn._prepare_non_root_persistent_volumes(
            name,
            disk,
            storage_av_zone,
            block_device_mapping,
            base_disk_index,
            existing_vim_volumes,
            created_items,
        )

        self.assertDictEqual(block_device_mapping, expected_block_device_mapping)
        self.assertEqual(existing_vim_volumes, expected_existing_vim_volumes)
        self.vimconn.cinder.volumes.create.assert_not_called()
        mock_update_block_device_mapping.assert_not_called()

    @patch.object(vimconnector, "update_block_device_mapping")
    def test_prepare_persistent_root_volumes_create(
        self, mock_update_block_device_mapping
    ):
        """Create persistent root volume."""
        self.vimconn.cinder.volumes.create.return_value.id = volume_id2
        storage_av_zone = ["nova"]
        base_disk_index = ord("a")
        disk = {"size": 10, "image_id": image_id}
        block_device_mapping = {}
        existing_vim_volumes = []
        created_items = {}
        expected_boot_vol_id = volume_id2
        boot_volume_id = self.vimconn._prepare_persistent_root_volumes(
            name,
            storage_av_zone,
            disk,
            base_disk_index,
            block_device_mapping,
            existing_vim_volumes,
            created_items,
        )
        self.assertEqual(boot_volume_id, expected_boot_vol_id)
        self.vimconn.cinder.volumes.create.assert_called_once_with(
            size=10,
            name="basicvmvda",
            imageRef=image_id,
            availability_zone=["nova"],
        )
        mock_update_block_device_mapping.assert_called_once()
        _call_mock_update_block_device_mapping = (
            mock_update_block_device_mapping.call_args_list
        )
        self.assertEqual(
            _call_mock_update_block_device_mapping[0].kwargs["block_device_mapping"],
            block_device_mapping,
        )
        self.assertEqual(
            _call_mock_update_block_device_mapping[0].kwargs["base_disk_index"], 97
        )
        self.assertEqual(_call_mock_update_block_device_mapping[0].kwargs["disk"], disk)
        self.assertEqual(
            _call_mock_update_block_device_mapping[0].kwargs["created_items"], {}
        )

    @patch.object(vimconnector, "update_block_device_mapping")
    def test_prepare_persistent_root_volumes_create_with_keep(
        self, mock_update_block_device_mapping
    ):
        """Create persistent root volume, disk has keep parameter."""
        self.vimconn.cinder.volumes.create.return_value.id = volume_id2
        storage_av_zone = ["nova"]
        base_disk_index = ord("a")
        disk = {"size": 10, "image_id": image_id, "keep": True}
        block_device_mapping = {}
        existing_vim_volumes = []
        created_items = {}
        expected_boot_vol_id = volume_id2
        expected_existing_vim_volumes = []
        boot_volume_id = self.vimconn._prepare_persistent_root_volumes(
            name,
            storage_av_zone,
            disk,
            base_disk_index,
            block_device_mapping,
            existing_vim_volumes,
            created_items,
        )
        self.assertEqual(boot_volume_id, expected_boot_vol_id)
        self.assertEqual(existing_vim_volumes, expected_existing_vim_volumes)
        self.vimconn.cinder.volumes.create.assert_called_once_with(
            size=10,
            name="basicvmvda",
            imageRef=image_id,
            availability_zone=["nova"],
        )
        mock_update_block_device_mapping.assert_called_once()
        _call_mock_update_block_device_mapping = (
            mock_update_block_device_mapping.call_args_list
        )
        self.assertEqual(
            _call_mock_update_block_device_mapping[0].kwargs["block_device_mapping"],
            block_device_mapping,
        )
        self.assertEqual(
            _call_mock_update_block_device_mapping[0].kwargs["base_disk_index"], 97
        )
        self.assertEqual(_call_mock_update_block_device_mapping[0].kwargs["disk"], disk)
        self.assertEqual(
            _call_mock_update_block_device_mapping[0].kwargs["created_items"], {}
        )

    @patch.object(vimconnector, "update_block_device_mapping")
    def test_prepare_persistent_non_root_volumes_create(
        self, mock_update_block_device_mapping
    ):
        """Create persistent non-root volume."""
        self.vimconn.cinder = CopyingMock()
        self.vimconn.cinder.volumes.create.return_value.id = volume_id2
        storage_av_zone = ["nova"]
        base_disk_index = ord("a")
        disk = {"size": 10}
        block_device_mapping = {}
        existing_vim_volumes = []
        created_items = {}
        expected_existing_vim_volumes = []
        self.vimconn._prepare_non_root_persistent_volumes(
            name,
            disk,
            storage_av_zone,
            block_device_mapping,
            base_disk_index,
            existing_vim_volumes,
            created_items,
        )

        self.assertEqual(existing_vim_volumes, expected_existing_vim_volumes)
        self.vimconn.cinder.volumes.create.assert_called_once_with(
            size=10, name="basicvmvda", availability_zone=["nova"]
        )
        mock_update_block_device_mapping.assert_called_once()
        _call_mock_update_block_device_mapping = (
            mock_update_block_device_mapping.call_args_list
        )
        self.assertEqual(
            _call_mock_update_block_device_mapping[0].kwargs["block_device_mapping"],
            block_device_mapping,
        )
        self.assertEqual(
            _call_mock_update_block_device_mapping[0].kwargs["base_disk_index"], 97
        )
        self.assertEqual(_call_mock_update_block_device_mapping[0].kwargs["disk"], disk)
        self.assertEqual(
            _call_mock_update_block_device_mapping[0].kwargs["created_items"], {}
        )

    @patch.object(vimconnector, "update_block_device_mapping")
    def test_prepare_persistent_non_root_volumes_create_with_keep(
        self, mock_update_block_device_mapping
    ):
        """Create persistent non-root volume."""
        self.vimconn.cinder = CopyingMock()
        self.vimconn.cinder.volumes.create.return_value.id = volume_id2
        storage_av_zone = ["nova"]
        base_disk_index = ord("a")
        disk = {"size": 10, "keep": True}
        block_device_mapping = {}
        existing_vim_volumes = []
        created_items = {}
        expected_existing_vim_volumes = []
        self.vimconn._prepare_non_root_persistent_volumes(
            name,
            disk,
            storage_av_zone,
            block_device_mapping,
            base_disk_index,
            existing_vim_volumes,
            created_items,
        )

        self.assertEqual(existing_vim_volumes, expected_existing_vim_volumes)
        self.vimconn.cinder.volumes.create.assert_called_once_with(
            size=10, name="basicvmvda", availability_zone=["nova"]
        )
        mock_update_block_device_mapping.assert_called_once()
        _call_mock_update_block_device_mapping = (
            mock_update_block_device_mapping.call_args_list
        )
        self.assertEqual(
            _call_mock_update_block_device_mapping[0].kwargs["block_device_mapping"],
            block_device_mapping,
        )
        self.assertEqual(
            _call_mock_update_block_device_mapping[0].kwargs["base_disk_index"], 97
        )
        self.assertEqual(_call_mock_update_block_device_mapping[0].kwargs["disk"], disk)
        self.assertEqual(
            _call_mock_update_block_device_mapping[0].kwargs["created_items"], {}
        )

    @patch.object(vimconnector, "update_block_device_mapping")
    def test_new_shared_volumes(self, mock_update_block_device_mapping):
        """Create shared volume."""

        class MyVolume:
            name = "my-shared-volume"
            id = volume_id4
            availability_zone = ["nova"]

        self.vimconn.storage_availability_zone = ["nova"]
        self.vimconn.cinder.volumes.create.return_value = MyVolume()
        shared_volume_data = {"size": 10, "name": "my-shared-volume"}
        result = self.vimconn.new_shared_volumes(shared_volume_data)
        self.vimconn.cinder.volumes.create.assert_called_once_with(
            size=10,
            name="my-shared-volume",
            volume_type="multiattach",
            availability_zone=["nova"],
        )
        self.assertEqual(result[0], "my-shared-volume")
        self.assertEqual(result[1], volume_id4)

    @patch.object(vimconnector, "update_block_device_mapping")
    def test_prepare_persistent_root_volumes_create_raise_exception(
        self, mock_update_block_device_mapping
    ):
        """Create persistent root volume raise exception."""
        self.vimconn.cinder.volumes.create.side_effect = Exception
        storage_av_zone = ["nova"]
        base_disk_index = ord("a")
        disk = {"size": 10, "image_id": image_id}
        block_device_mapping = {}
        existing_vim_volumes = []
        created_items = {}

        with self.assertRaises(Exception):
            result = self.vimconn._prepare_persistent_root_volumes(
                name,
                storage_av_zone,
                disk,
                base_disk_index,
                block_device_mapping,
                existing_vim_volumes,
                created_items,
            )

            self.assertEqual(result, None)

        self.vimconn.cinder.volumes.create.assert_called_once_with(
            size=10,
            name="basicvmvda",
            imageRef=image_id,
            availability_zone=["nova"],
        )
        self.assertEqual(existing_vim_volumes, [])
        self.assertEqual(block_device_mapping, {})
        self.assertEqual(created_items, {})
        mock_update_block_device_mapping.assert_not_called()

    @patch.object(vimconnector, "update_block_device_mapping")
    def test_prepare_persistent_non_root_volumes_create_raise_exception(
        self, mock_update_block_device_mapping
    ):
        """Create persistent non-root volume raise exception."""
        self.vimconn.cinder.volumes.create.side_effect = Exception
        storage_av_zone = ["nova"]
        base_disk_index = ord("b")
        disk = {"size": 10}
        block_device_mapping = {}
        existing_vim_volumes = []
        created_items = {}

        with self.assertRaises(Exception):
            self.vimconn._prepare_non_root_persistent_volumes(
                name,
                disk,
                storage_av_zone,
                block_device_mapping,
                base_disk_index,
                existing_vim_volumes,
                created_items,
            )

        self.vimconn.cinder.volumes.create.assert_called_once_with(
            size=10, name="basicvmvdb", availability_zone=["nova"]
        )
        self.assertEqual(existing_vim_volumes, [])
        self.assertEqual(block_device_mapping, {})
        self.assertEqual(created_items, {})
        mock_update_block_device_mapping.assert_not_called()

    @patch("time.sleep")
    def test_wait_for_created_volumes_availability_volume_status_available(
        self, mock_sleep
    ):
        """Created volume status is available."""
        elapsed_time = 5
        created_items = {f"volume:{volume_id2}": True}
        self.vimconn.cinder.volumes.get.return_value.status = "available"

        result = self.vimconn._wait_for_created_volumes_availability(
            elapsed_time, created_items
        )
        self.assertEqual(result, elapsed_time)
        self.vimconn.cinder.volumes.get.assert_called_with(volume_id2)
        mock_sleep.assert_not_called()

    @patch("time.sleep")
    def test_wait_for_existing_volumes_availability_volume_status_available(
        self, mock_sleep
    ):
        """Existing volume status is available."""
        elapsed_time = 5
        existing_vim_volumes = [{"id": volume_id2}]
        self.vimconn.cinder.volumes.get.return_value.status = "available"

        result = self.vimconn._wait_for_existing_volumes_availability(
            elapsed_time, existing_vim_volumes
        )
        self.assertEqual(result, elapsed_time)
        self.vimconn.cinder.volumes.get.assert_called_with(volume_id2)
        mock_sleep.assert_not_called()

    @patch("time.sleep")
    def test_wait_for_created_volumes_availability_status_processing_multiple_volumes(
        self, mock_sleep
    ):
        """Created volume status is processing."""
        elapsed_time = 5
        created_items = {
            f"volume:{volume_id2}": True,
            f"volume:{volume_id3}": True,
        }
        self.vimconn.cinder.volumes.get.side_effect = [
            Volume("processing"),
            Volume("available"),
            Volume("available"),
        ]

        result = self.vimconn._wait_for_created_volumes_availability(
            elapsed_time, created_items
        )
        self.assertEqual(result, 10)
        _call_mock_get_volumes = self.vimconn.cinder.volumes.get.call_args_list
        self.assertEqual(_call_mock_get_volumes[0][0], (volume_id2,))
        self.assertEqual(_call_mock_get_volumes[1][0], (volume_id2,))
        self.assertEqual(_call_mock_get_volumes[2][0], (volume_id3,))
        mock_sleep.assert_called_with(5)
        self.assertEqual(1, mock_sleep.call_count)

    @patch("time.sleep")
    def test_wait_for_existing_volumes_availability_status_processing_multiple_volumes(
        self, mock_sleep
    ):
        """Existing volume status is processing."""
        elapsed_time = 5
        existing_vim_volumes = [
            {"id": volume_id2},
            {"id": "44e0e83-b9uu-4akk-t234-p9cc4811bd4a"},
        ]
        self.vimconn.cinder.volumes.get.side_effect = [
            Volume("processing"),
            Volume("available", "multiattach"),
            Volume("available"),
        ]

        result = self.vimconn._wait_for_existing_volumes_availability(
            elapsed_time, existing_vim_volumes
        )
        self.assertEqual(result, 10)
        _call_mock_get_volumes = self.vimconn.cinder.volumes.get.call_args_list
        self.assertEqual(_call_mock_get_volumes[0][0], (volume_id2,))
        self.assertEqual(_call_mock_get_volumes[1][0], (volume_id2,))
        self.assertEqual(
            _call_mock_get_volumes[2][0], ("44e0e83-b9uu-4akk-t234-p9cc4811bd4a",)
        )
        mock_sleep.assert_called_with(5)
        self.assertEqual(1, mock_sleep.call_count)

    @patch("time.sleep")
    def test_wait_for_created_volumes_availability_volume_status_processing_timeout(
        self, mock_sleep
    ):
        """Created volume status is processing, elapsed time greater than timeout (1800)."""
        elapsed_time = 1805
        created_items = {f"volume:{volume_id2}": True}
        self.vimconn.cinder.volumes.get.side_effect = [
            Volume("processing"),
            Volume("processing"),
        ]
        with patch("time.sleep", mock_sleep):
            result = self.vimconn._wait_for_created_volumes_availability(
                elapsed_time, created_items
            )
            self.assertEqual(result, 1805)
        self.vimconn.cinder.volumes.get.assert_not_called()
        mock_sleep.assert_not_called()

    @patch("time.sleep")
    def test_wait_for_existing_volumes_availability_volume_status_processing_timeout(
        self, mock_sleep
    ):
        """Exsiting volume status is processing, elapsed time greater than timeout (1800)."""
        elapsed_time = 1805
        existing_vim_volumes = [{"id": volume_id2}]
        self.vimconn.cinder.volumes.get.side_effect = [
            Volume("processing"),
            Volume("processing"),
        ]

        result = self.vimconn._wait_for_existing_volumes_availability(
            elapsed_time, existing_vim_volumes
        )
        self.assertEqual(result, 1805)
        self.vimconn.cinder.volumes.get.assert_not_called()
        mock_sleep.assert_not_called()

    @patch("time.sleep")
    def test_wait_for_created_volumes_availability_cinder_raise_exception(
        self, mock_sleep
    ):
        """Cinder get volumes raises exception for created volumes."""
        elapsed_time = 1000
        created_items = {f"volume:{volume_id2}": True}
        self.vimconn.cinder.volumes.get.side_effect = Exception
        with self.assertRaises(Exception):
            result = self.vimconn._wait_for_created_volumes_availability(
                elapsed_time, created_items
            )
            self.assertEqual(result, 1000)
        self.vimconn.cinder.volumes.get.assert_called_with(volume_id2)
        mock_sleep.assert_not_called()

    @patch("time.sleep")
    def test_wait_for_existing_volumes_availability_cinder_raise_exception(
        self, mock_sleep
    ):
        """Cinder get volumes raises exception for existing volumes."""
        elapsed_time = 1000
        existing_vim_volumes = [{"id": volume_id2}]
        self.vimconn.cinder.volumes.get.side_effect = Exception
        with self.assertRaises(Exception):
            result = self.vimconn._wait_for_existing_volumes_availability(
                elapsed_time, existing_vim_volumes
            )
            self.assertEqual(result, 1000)
        self.vimconn.cinder.volumes.get.assert_called_with(volume_id2)
        mock_sleep.assert_not_called()

    @patch("time.sleep")
    def test_wait_for_created_volumes_availability_no_volume_in_created_items(
        self, mock_sleep
    ):
        """Created_items dict does not have volume-id."""
        elapsed_time = 10
        created_items = {}

        self.vimconn.cinder.volumes.get.side_effect = [None]

        result = self.vimconn._wait_for_created_volumes_availability(
            elapsed_time, created_items
        )
        self.assertEqual(result, 10)
        self.vimconn.cinder.volumes.get.assert_not_called()
        mock_sleep.assert_not_called()

    @patch("time.sleep")
    def test_wait_for_existing_volumes_availability_no_volume_in_existing_vim_volumes(
        self, mock_sleep
    ):
        """Existing_vim_volumes list does not have volume."""
        elapsed_time = 10
        existing_vim_volumes = []

        self.vimconn.cinder.volumes.get.side_effect = [None]

        result = self.vimconn._wait_for_existing_volumes_availability(
            elapsed_time, existing_vim_volumes
        )
        self.assertEqual(result, 10)
        self.vimconn.cinder.volumes.get.assert_not_called()
        mock_sleep.assert_not_called()

    @patch.object(vimconnector, "_prepare_persistent_root_volumes")
    @patch.object(vimconnector, "_prepare_non_root_persistent_volumes")
    @patch.object(vimconnector, "_wait_for_created_volumes_availability")
    @patch.object(vimconnector, "_wait_for_existing_volumes_availability")
    def test_prepare_disk_for_vm_instance(
        self,
        mock_existing_vol_availability,
        mock_created_vol_availability,
        mock_non_root_volumes,
        mock_root_volumes,
    ):
        """Prepare disks for VM instance successfully."""
        existing_vim_volumes = []
        created_items = {}
        block_device_mapping = {}
        storage_av_zone = ["nova"]

        mock_root_volumes.return_value = root_vol_id
        mock_created_vol_availability.return_value = 10
        mock_existing_vol_availability.return_value = 15
        self.vimconn.cinder = CopyingMock()
        self.vimconn._prepare_disk_for_vminstance(
            name,
            existing_vim_volumes,
            created_items,
            storage_av_zone,
            block_device_mapping,
            disk_list2,
        )
        self.vimconn.cinder.volumes.set_bootable.assert_called_once_with(
            root_vol_id, True
        )
        mock_created_vol_availability.assert_called_once_with(0, created_items)
        mock_existing_vol_availability.assert_called_once_with(10, existing_vim_volumes)
        self.assertEqual(mock_root_volumes.call_count, 1)
        self.assertEqual(mock_non_root_volumes.call_count, 1)
        mock_root_volumes.assert_called_once_with(
            name="basicvm",
            storage_av_zone=["nova"],
            disk={"size": 10, "image_id": image_id},
            base_disk_index=97,
            block_device_mapping={},
            existing_vim_volumes=[],
            created_items={},
        )
        mock_non_root_volumes.assert_called_once_with(
            name="basicvm",
            disk={"size": 20},
            storage_av_zone=["nova"],
            base_disk_index=98,
            block_device_mapping={},
            existing_vim_volumes=[],
            created_items={},
        )

    @patch.object(vimconnector, "_prepare_persistent_root_volumes")
    @patch.object(vimconnector, "_prepare_non_root_persistent_volumes")
    @patch.object(vimconnector, "_wait_for_created_volumes_availability")
    @patch.object(vimconnector, "_wait_for_existing_volumes_availability")
    def test_prepare_disk_for_vm_instance_timeout_exceeded(
        self,
        mock_existing_vol_availability,
        mock_created_vol_availability,
        mock_non_root_volumes,
        mock_root_volumes,
    ):
        """Timeout exceeded while waiting for disks."""
        existing_vim_volumes = []
        created_items = {}
        storage_av_zone = ["nova"]
        block_device_mapping = {}

        mock_root_volumes.return_value = root_vol_id
        mock_created_vol_availability.return_value = 1700
        mock_existing_vol_availability.return_value = 1900

        with self.assertRaises(VimConnException) as err:
            self.vimconn._prepare_disk_for_vminstance(
                name,
                existing_vim_volumes,
                created_items,
                storage_av_zone,
                block_device_mapping,
                disk_list2,
            )
        self.assertEqual(
            str(err.exception), "Timeout creating volumes for instance basicvm"
        )
        self.vimconn.cinder.volumes.set_bootable.assert_not_called()
        mock_created_vol_availability.assert_called_once_with(0, created_items)
        mock_existing_vol_availability.assert_called_once_with(
            1700, existing_vim_volumes
        )
        self.assertEqual(mock_root_volumes.call_count, 1)
        self.assertEqual(mock_non_root_volumes.call_count, 1)
        mock_root_volumes.assert_called_once_with(
            name="basicvm",
            storage_av_zone=["nova"],
            disk={"size": 10, "image_id": image_id},
            base_disk_index=97,
            block_device_mapping={},
            existing_vim_volumes=[],
            created_items={},
        )
        mock_non_root_volumes.assert_called_once_with(
            name="basicvm",
            disk={"size": 20},
            storage_av_zone=["nova"],
            base_disk_index=98,
            block_device_mapping={},
            existing_vim_volumes=[],
            created_items={},
        )

    @patch.object(vimconnector, "_prepare_persistent_root_volumes")
    @patch.object(vimconnector, "_prepare_non_root_persistent_volumes")
    @patch.object(vimconnector, "_wait_for_created_volumes_availability")
    @patch.object(vimconnector, "_wait_for_existing_volumes_availability")
    def test_prepare_disk_for_vm_instance_empty_disk_list(
        self,
        mock_existing_vol_availability,
        mock_created_vol_availability,
        mock_non_root_volumes,
        mock_root_volumes,
    ):
        """Disk list is empty."""
        existing_vim_volumes = []
        created_items = {}
        block_device_mapping = {}
        storage_av_zone = ["nova"]
        mock_created_vol_availability.return_value = 2
        mock_existing_vol_availability.return_value = 3

        self.vimconn._prepare_disk_for_vminstance(
            name,
            existing_vim_volumes,
            created_items,
            storage_av_zone,
            block_device_mapping,
            disk_list,
        )
        self.vimconn.cinder.volumes.set_bootable.assert_not_called()
        mock_created_vol_availability.assert_called_once_with(0, created_items)
        mock_existing_vol_availability.assert_called_once_with(2, existing_vim_volumes)
        mock_root_volumes.assert_not_called()
        mock_non_root_volumes.assert_not_called()

    @patch.object(vimconnector, "_prepare_persistent_root_volumes")
    @patch.object(vimconnector, "_prepare_non_root_persistent_volumes")
    @patch.object(vimconnector, "_wait_for_created_volumes_availability")
    @patch.object(vimconnector, "_wait_for_existing_volumes_availability")
    def test_prepare_disk_for_vm_instance_persistent_root_volume_error(
        self,
        mock_existing_vol_availability,
        mock_created_vol_availability,
        mock_non_root_volumes,
        mock_root_volumes,
    ):
        """Persistent root volumes preparation raises error."""
        existing_vim_volumes = []
        created_items = {}
        storage_av_zone = ["nova"]
        block_device_mapping = {}

        mock_root_volumes.side_effect = Exception()
        mock_created_vol_availability.return_value = 10
        mock_existing_vol_availability.return_value = 15

        with self.assertRaises(Exception):
            self.vimconn._prepare_disk_for_vminstance(
                name,
                existing_vim_volumes,
                created_items,
                storage_av_zone,
                block_device_mapping,
                disk_list2,
            )
        self.vimconn.cinder.volumes.set_bootable.assert_not_called()
        mock_created_vol_availability.assert_not_called()
        mock_existing_vol_availability.assert_not_called()
        mock_root_volumes.assert_called_once_with(
            name="basicvm",
            storage_av_zone=["nova"],
            disk={"size": 10, "image_id": image_id},
            base_disk_index=97,
            block_device_mapping={},
            existing_vim_volumes=[],
            created_items={},
        )
        mock_non_root_volumes.assert_not_called()

    @patch.object(vimconnector, "_prepare_persistent_root_volumes")
    @patch.object(vimconnector, "_prepare_non_root_persistent_volumes")
    @patch.object(vimconnector, "_wait_for_created_volumes_availability")
    @patch.object(vimconnector, "_wait_for_existing_volumes_availability")
    def test_prepare_disk_for_vm_instance_non_root_volume_error(
        self,
        mock_existing_vol_availability,
        mock_created_vol_availability,
        mock_non_root_volumes,
        mock_root_volumes,
    ):
        """Non-root volumes preparation raises error."""
        existing_vim_volumes = []
        created_items = {}
        storage_av_zone = ["nova"]
        block_device_mapping = {}

        mock_root_volumes.return_value = root_vol_id
        mock_non_root_volumes.side_effect = Exception

        with self.assertRaises(Exception):
            self.vimconn._prepare_disk_for_vminstance(
                name,
                existing_vim_volumes,
                created_items,
                storage_av_zone,
                block_device_mapping,
                disk_list2,
            )
        self.vimconn.cinder.volumes.set_bootable.assert_not_called()
        mock_created_vol_availability.assert_not_called()
        mock_existing_vol_availability.assert_not_called()
        self.assertEqual(mock_root_volumes.call_count, 1)
        self.assertEqual(mock_non_root_volumes.call_count, 1)
        mock_root_volumes.assert_called_once_with(
            name="basicvm",
            storage_av_zone=["nova"],
            disk={"size": 10, "image_id": image_id},
            base_disk_index=97,
            block_device_mapping={},
            existing_vim_volumes=[],
            created_items={},
        )
        mock_non_root_volumes.assert_called_once_with(
            name="basicvm",
            disk={"size": 20},
            storage_av_zone=["nova"],
            base_disk_index=98,
            block_device_mapping={},
            existing_vim_volumes=[],
            created_items={},
        )

    def test_find_external_network_for_floating_ip_no_external_network(self):
        """External network could not be found."""
        self.vimconn.neutron.list_networks.return_value = {
            "networks": [
                {"id": "408b73-r9cc-5a6a-a270-82cc4811bd4a", "router:external": False}
            ]
        }
        with self.assertRaises(VimConnException) as err:
            self.vimconn._find_the_external_network_for_floating_ip()
        self.assertEqual(
            str(err.exception),
            "Cannot create floating_ip automatically since no external network is present",
        )

    def test_find_external_network_for_floating_one_external_network(self):
        """One external network has been found."""
        self.vimconn.neutron.list_networks.return_value = {
            "networks": [
                {"id": "408b73-r9cc-5a6a-a270-82cc4811bd4a", "router:external": True}
            ]
        }
        expected_result = "408b73-r9cc-5a6a-a270-82cc4811bd4a"
        result = self.vimconn._find_the_external_network_for_floating_ip()
        self.assertEqual(result, expected_result)

    def test_find_external_network_for_floating_neutron_raises_exception(self):
        """Neutron list networks raises exception."""
        self.vimconn.neutron.list_networks.side_effect = Exception
        with self.assertRaises(Exception):
            self.vimconn._find_the_external_network_for_floating_ip()

    def test_find_external_network_for_floating_several_external_network(self):
        """Several exernal networks has been found."""
        self.vimconn.neutron.list_networks.return_value = {
            "networks": [
                {"id": "408b73-r9cc-5a6a-a270-82cc4811bd4a", "router:external": True},
                {"id": "608b73-y9cc-5a6a-a270-12cc4811bd4a", "router:external": True},
            ]
        }
        with self.assertRaises(VimConnException) as err:
            self.vimconn._find_the_external_network_for_floating_ip()
        self.assertEqual(
            str(err.exception),
            "Cannot create floating_ip automatically since multiple external networks are present",
        )

    def test_neutron_create_float_ip(self):
        """Floating ip creation is successful."""
        param = {"net_id": "408b73-r9cc-5a6a-a270-p2cc4811bd9a"}
        created_items = {}
        self.vimconn.neutron.create_floatingip.return_value = {
            "floatingip": {"id": "308b73-t9cc-1a6a-a270-12cc4811bd4a"}
        }
        expected_created_items = {
            "floating_ip:308b73-t9cc-1a6a-a270-12cc4811bd4a": True
        }
        self.vimconn._neutron_create_float_ip(param, created_items)
        self.assertEqual(created_items, expected_created_items)

    def test_neutron_create_float_ip_exception_occurred(self):
        """Floating ip could not be created."""
        param = {
            "floatingip": {
                "floating_network_id": "408b73-r9cc-5a6a-a270-p2cc4811bd9a",
                "tenant_id": "308b73-19cc-8a6a-a270-02cc4811bd9a",
            }
        }
        created_items = {}
        self.vimconn.neutron = CopyingMock()
        self.vimconn.neutron.create_floatingip.side_effect = Exception(
            "Neutron floating ip create exception occurred."
        )
        with self.assertRaises(VimConnException) as err:
            self.vimconn._neutron_create_float_ip(param, created_items)
        self.assertEqual(created_items, {})
        self.assertEqual(
            str(err.exception),
            "Exception: Cannot create new floating_ip Neutron floating ip create exception occurred.",
        )

    @patch.object(vimconnector, "_neutron_create_float_ip")
    @patch.object(vimconnector, "_find_the_external_network_for_floating_ip")
    def test_create_floating_ip_pool_id_available(
        self, mock_find_ext_network, mock_create_float_ip
    ):
        """Floating ip creation, ip pool is available."""
        floating_network = {"floating_ip": "308b73-t9cc-1a6a-a270-12cc4811bd4a"}
        created_items = {}
        expected_param = {
            "floatingip": {
                "floating_network_id": "308b73-t9cc-1a6a-a270-12cc4811bd4a",
                "tenant_id": "408b73-r9cc-5a6a-a270-82cc4811bd4a",
            }
        }
        self.vimconn._create_floating_ip(floating_network, self.server, created_items)
        mock_find_ext_network.assert_not_called()
        mock_create_float_ip.assert_called_once_with(expected_param, {})

    @patch.object(vimconnector, "_neutron_create_float_ip")
    @patch.object(vimconnector, "_find_the_external_network_for_floating_ip")
    def test_create_floating_ip_finding_pool_id(
        self, mock_find_ext_network, mock_create_float_ip
    ):
        """Floating ip creation, pool id need to be found."""
        floating_network = {"floating_ip": True}
        created_items = {}
        mock_find_ext_network.return_value = "308b73-t9cc-1a6a-a270-12cc4811bd4a"
        expected_param = {
            "floatingip": {
                "floating_network_id": "308b73-t9cc-1a6a-a270-12cc4811bd4a",
                "tenant_id": "408b73-r9cc-5a6a-a270-82cc4811bd4a",
            }
        }
        self.vimconn._create_floating_ip(floating_network, self.server, created_items)
        mock_find_ext_network.assert_called_once()
        mock_create_float_ip.assert_called_once_with(expected_param, {})

    @patch.object(vimconnector, "_neutron_create_float_ip")
    @patch.object(vimconnector, "_find_the_external_network_for_floating_ip")
    def test_create_floating_ip_neutron_create_floating_ip_exception(
        self, mock_find_ext_network, mock_create_float_ip
    ):
        """Neutron creat floating ip raises error."""
        floating_network = {"floating_ip": True}
        created_items = {}
        mock_create_float_ip.side_effect = VimConnException(
            "Can not create floating ip."
        )
        mock_find_ext_network.return_value = "308b73-t9cc-1a6a-a270-12cc4811bd4a"
        expected_param = {
            "floatingip": {
                "floating_network_id": "308b73-t9cc-1a6a-a270-12cc4811bd4a",
                "tenant_id": "408b73-r9cc-5a6a-a270-82cc4811bd4a",
            }
        }

        with self.assertRaises(VimConnException) as err:
            self.vimconn._create_floating_ip(
                floating_network, self.server, created_items
            )
        self.assertEqual(str(err.exception), "Can not create floating ip.")
        mock_find_ext_network.assert_called_once()
        mock_create_float_ip.assert_called_once_with(expected_param, {})

    @patch.object(vimconnector, "_neutron_create_float_ip")
    @patch.object(vimconnector, "_find_the_external_network_for_floating_ip")
    def test_create_floating_ip_can_not_find_pool_id(
        self, mock_find_ext_network, mock_create_float_ip
    ):
        """Floating ip creation, pool id could not be found."""
        floating_network = {"floating_ip": True}
        created_items = {}
        mock_find_ext_network.side_effect = VimConnException(
            "Cannot create floating_ip automatically since no external network is present"
        )
        with self.assertRaises(VimConnException) as err:
            self.vimconn._create_floating_ip(
                floating_network, self.server, created_items
            )
        self.assertEqual(
            str(err.exception),
            "Cannot create floating_ip automatically since no external network is present",
        )
        mock_find_ext_network.assert_called_once()
        mock_create_float_ip.assert_not_called()

    def test_find_floating_ip_get_free_floating_ip(self):
        """Get free floating ips successfully."""
        floating_ips = [
            {
                "tenant_id": "408b73-r9cc-5a6a-a270-82cc4811bd4a",
                "floating_network_id": "308b73-t9cc-1a6a-a270-12cc4811bd4a",
                "id": "508b73-o9cc-5a6a-a270-72cc4811bd8",
            }
        ]
        floating_network = {"floating_ip": "308b73-t9cc-1a6a-a270-12cc4811bd4a"}
        expected_result = "508b73-o9cc-5a6a-a270-72cc4811bd8"

        result = self.vimconn._find_floating_ip(
            self.server, floating_ips, floating_network
        )
        self.assertEqual(result, expected_result)

    def test_find_floating_ip_different_floating_network_id(self):
        """Floating network id is different with floating_ip of floating network."""
        floating_ips = [
            {
                "floating_network_id": "308b73-t9cc-1a6a-a270-12cc4811bd4a",
                "id": "508b73-o9cc-5a6a-a270-72cc4811bd8",
            }
        ]
        floating_network = {"floating_ip": "508b73-t9cc-1a6a-a270-12cc4811bd4a"}

        result = self.vimconn._find_floating_ip(
            self.server, floating_ips, floating_network
        )
        self.assertEqual(result, None)

    def test_find_floating_ip_different_fip_tenant(self):
        """Items in floating_ips has port_id, tenant_is is not same with server tenant id."""
        floating_ips = [
            {
                "port_id": "608b73-r9cc-5a6a-a270-82cc4811bd4a",
                "floating_network_id": "308b73-t9cc-1a6a-a270-12cc4811bd4a",
                "id": "508b73-o9cc-5a6a-a270-72cc4811bd8",
                "tenant_id": self.server.id,
            }
        ]
        floating_network = {"floating_ip": "308b73-t9cc-1a6a-a270-12cc4811bd4a"}
        mock_create_floating_ip = CopyingMock()
        with patch.object(vimconnector, "_create_floating_ip", mock_create_floating_ip):
            result = self.vimconn._find_floating_ip(
                self.server, floating_ips, floating_network
            )
            self.assertEqual(result, None)

    @patch("time.sleep")
    def test_assign_floating_ip(self, mock_sleep):
        """Assign floating ip successfully."""
        free_floating_ip = "508b73-o9cc-5a6a-a270-72cc4811bd8"
        floating_network = {"vim_id": floating_network_vim_id}
        fip = {
            "port_id": floating_network_vim_id,
            "floating_network_id": "p08b73-e9cc-5a6a-t270-82cc4811bd4a",
            "id": "508b73-o9cc-5a6a-a270-72cc4811bd8",
            "tenant_id": "k08b73-e9cc-5a6a-t270-82cc4811bd4a",
        }
        self.vimconn.neutron.update_floatingip.side_effect = None
        self.vimconn.neutron.show_floatingip.return_value = fip
        expected_result = fip

        result = self.vimconn._assign_floating_ip(free_floating_ip, floating_network)
        self.assertEqual(result, expected_result)
        self.vimconn.neutron.update_floatingip.assert_called_once_with(
            free_floating_ip,
            {"floatingip": {"port_id": floating_network_vim_id}},
        )
        mock_sleep.assert_called_once_with(5)
        self.vimconn.neutron.show_floatingip.assert_called_once_with(free_floating_ip)

    @patch("time.sleep")
    def test_assign_floating_ip_update_floating_ip_exception(self, mock_sleep):
        """Neutron update floating ip raises exception."""
        free_floating_ip = "508b73-o9cc-5a6a-a270-72cc4811bd8"
        floating_network = {"vim_id": floating_network_vim_id}
        self.vimconn.neutron = CopyingMock()
        self.vimconn.neutron.update_floatingip.side_effect = Exception(
            "Floating ip is not updated."
        )

        with self.assertRaises(Exception) as err:
            result = self.vimconn._assign_floating_ip(
                free_floating_ip, floating_network
            )
            self.assertEqual(result, None)
        self.assertEqual(str(err.exception), "Floating ip is not updated.")

        self.vimconn.neutron.update_floatingip.assert_called_once_with(
            free_floating_ip,
            {"floatingip": {"port_id": floating_network_vim_id}},
        )
        mock_sleep.assert_not_called()
        self.vimconn.neutron.show_floatingip.assert_not_called()

    @patch("time.sleep")
    def test_assign_floating_ip_show_floating_ip_exception(self, mock_sleep):
        """Neutron show floating ip raises exception."""
        free_floating_ip = "508b73-o9cc-5a6a-a270-72cc4811bd8"
        floating_network = {"vim_id": floating_network_vim_id}
        self.vimconn.neutron.update_floatingip.side_effect = None
        self.vimconn.neutron.show_floatingip.side_effect = Exception(
            "Floating ip could not be shown."
        )

        with self.assertRaises(Exception) as err:
            result = self.vimconn._assign_floating_ip(
                free_floating_ip, floating_network
            )
            self.assertEqual(result, None)
            self.assertEqual(str(err.exception), "Floating ip could not be shown.")
        self.vimconn.neutron.update_floatingip.assert_called_once_with(
            free_floating_ip,
            {"floatingip": {"port_id": floating_network_vim_id}},
        )
        mock_sleep.assert_called_once_with(5)
        self.vimconn.neutron.show_floatingip.assert_called_once_with(free_floating_ip)

    @patch("random.shuffle")
    @patch.object(vimconnector, "_find_floating_ip")
    def test_get_free_floating_ip(self, mock_find_floating_ip, mock_shuffle):
        """Get free floating ip successfully."""
        floating_network = {"floating_ip": "308b73-t9cc-1a6a-a270-12cc4811bd4a"}
        floating_ips = [
            {
                "port_id": "608b73-r9cc-5a6a-a270-82cc4811bd4a",
                "floating_network_id": "308b73-t9cc-1a6a-a270-12cc4811bd4a",
                "id": "508b73-o9cc-5a6a-a270-72cc4811bd8",
                "tenant_id": "208b73-e9cc-5a6a-t270-82cc4811bd4a",
            },
            {
                "port_id": "508b73-r9cc-5a6a-5270-o2cc4811bd4a",
                "floating_network_id": "308b73-t9cc-1a6a-a270-12cc4811bd4a",
                "id": "208b73-o9cc-5a6a-a270-52cc4811bd8",
                "tenant_id": "208b73-e9cc-5a6a-t270-82cc4811bd4a",
            },
        ]
        self.vimconn.neutron.list_floatingips.return_value = {
            "floatingips": floating_ips
        }
        mock_find_floating_ip.return_value = "508b73-o9cc-5a6a-a270-72cc4811bd8"
        expected_result = "508b73-o9cc-5a6a-a270-72cc4811bd8"

        result = self.vimconn._get_free_floating_ip(self.server, floating_network)
        self.assertEqual(result, expected_result)
        mock_shuffle.assert_called_once_with(floating_ips)
        mock_find_floating_ip.assert_called_once_with(
            self.server, floating_ips, floating_network
        )

    @patch("random.shuffle")
    @patch.object(vimconnector, "_find_floating_ip")
    def test_get_free_floating_ip_list_floating_ip_exception(
        self, mock_find_floating_ip, mock_shuffle
    ):
        """Neutron list floating IPs raises exception."""
        floating_network = {"floating_ip": "308b73-t9cc-1a6a-a270-12cc4811bd4a"}
        self.vimconn.neutron = CopyingMock()
        self.vimconn.neutron.list_floatingips.side_effect = Exception(
            "Floating ips could not be listed."
        )
        with self.assertRaises(Exception) as err:
            result = self.vimconn._get_free_floating_ip(self.server, floating_network)
            self.assertEqual(result, None)
            self.assertEqual(str(err.exception), "Floating ips could not be listed.")
        mock_shuffle.assert_not_called()
        mock_find_floating_ip.assert_not_called()

    @patch("random.shuffle")
    @patch.object(vimconnector, "_find_floating_ip")
    def test_get_free_floating_ip_find_floating_ip_exception(
        self, mock_find_floating_ip, mock_shuffle
    ):
        """_find_floating_ip method raises exception."""
        floating_network = {"floating_ip": "308b73-t9cc-1a6a-a270-12cc4811bd4a"}
        floating_ips = [
            {
                "port_id": "608b73-r9cc-5a6a-a270-82cc4811bd4a",
                "floating_network_id": "308b73-t9cc-1a6a-a270-12cc4811bd4a",
                "id": "508b73-o9cc-5a6a-a270-72cc4811bd8",
                "tenant_id": "208b73-e9cc-5a6a-t270-82cc4811bd4a",
            },
            {
                "port_id": "508b73-r9cc-5a6a-5270-o2cc4811bd4a",
                "floating_network_id": "308b73-t9cc-1a6a-a270-12cc4811bd4a",
                "id": "208b73-o9cc-5a6a-a270-52cc4811bd8",
                "tenant_id": "208b73-e9cc-5a6a-t270-82cc4811bd4a",
            },
        ]
        self.vimconn.neutron = CopyingMock()
        self.vimconn.neutron.list_floatingips.return_value = {
            "floatingips": floating_ips
        }
        mock_find_floating_ip.side_effect = Exception(
            "Free floating ip could not be found."
        )

        with self.assertRaises(Exception) as err:
            result = self.vimconn._get_free_floating_ip(self.server, floating_network)
            self.assertEqual(result, None)
            self.assertEqual(str(err.exception), "Free floating ip could not be found.")
        mock_shuffle.assert_called_once_with(floating_ips)
        mock_find_floating_ip.assert_called_once_with(
            self.server, floating_ips, floating_network
        )

    @patch.object(vimconnector, "_create_floating_ip")
    @patch.object(vimconnector, "_get_free_floating_ip")
    @patch.object(vimconnector, "_assign_floating_ip")
    def test_prepare_external_network_for_vm_instance(
        self,
        mock_assign_floating_ip,
        mock_get_free_floating_ip,
        mock_create_floating_ip,
    ):
        """Prepare external network successfully."""
        external_network = [
            {
                "floating_ip": "y08b73-o9cc-1a6a-a270-12cc4811bd4u",
                "vim_id": "608b73-r9cc-5a6a-a270-82cc4811bd4a",
            },
        ]
        created_items = {}
        vm_start_time = time_return_value
        mock_get_free_floating_ip.side_effect = ["y08b73-o9cc-1a6a-a270-12cc4811bd4u"]
        mock_assign_floating_ip.return_value = {
            "floatingip": {"port_id": "608b73-r9cc-5a6a-a270-82cc4811bd4a"}
        }
        self.vimconn.neutron = CopyingMock()
        self.vimconn.nova = CopyingMock()
        self.vimconn.neutron.show_floatingip.return_value = {
            "floatingip": {"port_id": ""}
        }

        self.vimconn._prepare_external_network_for_vminstance(
            external_network, self.server, created_items, vm_start_time
        )

        self.assertEqual(mock_get_free_floating_ip.call_count, 1)
        mock_get_free_floating_ip.assert_called_once_with(
            self.server,
            {
                "floating_ip": "y08b73-o9cc-1a6a-a270-12cc4811bd4u",
                "vim_id": "608b73-r9cc-5a6a-a270-82cc4811bd4a",
            },
        )
        self.vimconn.neutron.show_floatingip.assert_called_once_with(
            "y08b73-o9cc-1a6a-a270-12cc4811bd4u"
        )
        self.vimconn.nova.servers.get.assert_not_called()
        mock_create_floating_ip.assert_not_called()
        mock_assign_floating_ip.assert_called_once_with(
            "y08b73-o9cc-1a6a-a270-12cc4811bd4u",
            {
                "floating_ip": "y08b73-o9cc-1a6a-a270-12cc4811bd4u",
                "vim_id": "608b73-r9cc-5a6a-a270-82cc4811bd4a",
            },
        )

    @patch("time.time")
    @patch("time.sleep")
    @patch.object(vimconnector, "_create_floating_ip")
    @patch.object(vimconnector, "_get_free_floating_ip")
    @patch.object(vimconnector, "_assign_floating_ip")
    def test_prepare_external_network_for_vm_instance_no_free_floating_ip(
        self,
        mock_assign_floating_ip,
        mock_get_free_floating_ip,
        mock_create_floating_ip,
        mock_sleep,
        mock_time,
    ):
        """There is not any free floating ip."""
        floating_network = {
            "floating_ip": "y08b73-o9cc-1a6a-a270-12cc4811bd4u",
            "vim_id": "608b73-r9cc-5a6a-a270-82cc4811bd4a",
        }
        external_network = [floating_network]

        created_items = {}
        vm_start_time = time_return_value
        mock_get_free_floating_ip.return_value = None
        mock_assign_floating_ip.return_value = {}
        self.vimconn.nova.servers.get.return_value.status = "ERROR"
        self.vimconn.neutron.show_floatingip.return_value = {}

        with self.assertRaises(KeyError):
            self.vimconn._prepare_external_network_for_vminstance(
                external_network, self.server, created_items, vm_start_time
            )

        self.assertEqual(mock_get_free_floating_ip.call_count, 4)
        mock_get_free_floating_ip.assert_called_with(
            self.server,
            {
                "floating_ip": "y08b73-o9cc-1a6a-a270-12cc4811bd4u",
                "vim_id": "608b73-r9cc-5a6a-a270-82cc4811bd4a",
            },
        )
        self.vimconn.neutron.show_floatingip.assert_called_with(None)
        mock_sleep.assert_not_called()
        mock_time.assert_not_called()
        self.assertEqual(self.vimconn.nova.servers.get.call_count, 4)
        mock_create_floating_ip.assert_called_with(
            floating_network, self.server, created_items
        )
        self.assertEqual(mock_create_floating_ip.call_count, 4)
        mock_assign_floating_ip.assert_not_called()
        self.vimconn.nova.servers.get.assert_called_with(self.server.id)

    @patch("time.time")
    @patch("time.sleep")
    @patch.object(vimconnector, "_create_floating_ip")
    @patch.object(vimconnector, "_get_free_floating_ip")
    @patch.object(vimconnector, "_assign_floating_ip")
    def test_prepare_external_network_for_vm_instance_no_free_fip_can_not_create_fip_exit_on_error_false(
        self,
        mock_assign_floating_ip,
        mock_get_free_floating_ip,
        mock_create_floating_ip,
        mock_sleep,
        mock_time,
    ):
        """There is not any free floating ip, create_floating ip method raise exception
        exit_on_floating_ip_error set to False."""
        floating_network = {
            "floating_ip": "y08b73-o9cc-1a6a-a270-12cc4811bd4u",
            "vim_id": "608b73-r9cc-5a6a-a270-82cc4811bd4a",
            "exit_on_floating_ip_error": False,
        }
        external_network = [floating_network]

        created_items = {}
        vm_start_time = time_return_value
        mock_get_free_floating_ip.return_value = None
        mock_assign_floating_ip.return_value = {}
        mock_create_floating_ip.side_effect = VimConnException(
            "Can not create floating ip."
        )
        self.vimconn.nova.servers.get.return_value.status = "ERROR"
        self.vimconn.neutron.show_floatingip.return_value = {}

        self.vimconn._prepare_external_network_for_vminstance(
            external_network, self.server, created_items, vm_start_time
        )
        self.assertEqual(mock_get_free_floating_ip.call_count, 1)
        mock_get_free_floating_ip.assert_called_with(
            self.server,
            {
                "floating_ip": "y08b73-o9cc-1a6a-a270-12cc4811bd4u",
                "vim_id": "608b73-r9cc-5a6a-a270-82cc4811bd4a",
                "exit_on_floating_ip_error": False,
            },
        )
        self.vimconn.neutron.show_floatingip.assert_not_called()
        mock_sleep.assert_not_called()
        mock_time.assert_not_called()
        self.vimconn.nova.servers.get.assert_not_called()
        mock_create_floating_ip.assert_called_with(
            floating_network, self.server, created_items
        )
        self.assertEqual(mock_create_floating_ip.call_count, 1)
        mock_assign_floating_ip.assert_not_called()

    @patch("time.time")
    @patch("time.sleep")
    @patch.object(vimconnector, "_create_floating_ip")
    @patch.object(vimconnector, "_get_free_floating_ip")
    @patch.object(vimconnector, "_assign_floating_ip")
    def test_prepare_external_network_for_vm_instance_no_free_fip_can_not_create_fip_exit_on_error_true(
        self,
        mock_assign_floating_ip,
        mock_get_free_floating_ip,
        mock_create_floating_ip,
        mock_sleep,
        mock_time,
    ):
        """There is not any free floating ip, create_floating ip method raise exception
        exit_on_floating_ip_error set to False."""
        floating_network = {
            "floating_ip": "y08b73-o9cc-1a6a-a270-12cc4811bd4u",
            "vim_id": "608b73-r9cc-5a6a-a270-82cc4811bd4a",
            "exit_on_floating_ip_error": True,
        }
        external_network = [floating_network]

        created_items = {}
        vm_start_time = time_return_value
        mock_get_free_floating_ip.return_value = None
        mock_assign_floating_ip.return_value = {}
        mock_create_floating_ip.side_effect = VimConnException(
            "Can not create floating ip."
        )
        self.vimconn.nova.servers.get.return_value.status = "ERROR"
        self.vimconn.neutron.show_floatingip.return_value = {}
        with self.assertRaises(VimConnException):
            self.vimconn._prepare_external_network_for_vminstance(
                external_network, self.server, created_items, vm_start_time
            )
        self.assertEqual(mock_get_free_floating_ip.call_count, 1)
        mock_get_free_floating_ip.assert_called_with(
            self.server,
            {
                "floating_ip": "y08b73-o9cc-1a6a-a270-12cc4811bd4u",
                "vim_id": "608b73-r9cc-5a6a-a270-82cc4811bd4a",
                "exit_on_floating_ip_error": True,
            },
        )
        self.vimconn.neutron.show_floatingip.assert_not_called()
        mock_sleep.assert_not_called()
        mock_time.assert_not_called()
        self.vimconn.nova.servers.get.assert_not_called()
        mock_create_floating_ip.assert_called_with(
            floating_network, self.server, created_items
        )
        self.assertEqual(mock_create_floating_ip.call_count, 1)
        mock_assign_floating_ip.assert_not_called()

    @patch.object(vimconnector, "_create_floating_ip")
    @patch.object(vimconnector, "_get_free_floating_ip")
    @patch.object(vimconnector, "_assign_floating_ip")
    def test_prepare_external_network_for_vm_instance_fip_has_port_id(
        self,
        mock_assign_floating_ip,
        mock_get_free_floating_ip,
        mock_create_floating_ip,
    ):
        """Neutron show floating ip return the fip with port_id and floating network vim_id
        is different from port_id."""
        floating_network = {
            "floating_ip": "y08b73-o9cc-1a6a-a270-12cc4811bd4u",
            "vim_id": "608b73-r9cc-5a6a-a270-82cc4811bd4a",
        }
        external_network = [floating_network]
        created_items = {}
        vm_start_time = 150
        mock_get_free_floating_ip.side_effect = [
            "t08b73-o9cc-1a6a-a270-12cc4811bd4u",
            "r08b73-o9cc-1a6a-a270-12cc4811bd4u",
            "y08b73-o9cc-1a6a-a270-12cc4811bd4u",
        ]
        mock_assign_floating_ip.side_effect = [
            {"floatingip": {"port_id": "k08b73-r9cc-5a6a-a270-82cc4811bd4a"}},
            {"floatingip": {"port_id": "608b73-r9cc-5a6a-a270-82cc4811bd4a"}},
        ]
        self.vimconn.neutron = CopyingMock()
        self.vimconn.nova = CopyingMock()
        self.vimconn.neutron.show_floatingip.side_effect = [
            {"floatingip": {"port_id": "608b73-r9cc-5a6a-a270-82cc4811bd4a"}},
            {"floatingip": {"port_id": ""}},
            {"floatingip": {"port_id": ""}},
        ]
        self.vimconn._prepare_external_network_for_vminstance(
            external_network, self.server, created_items, vm_start_time
        )
        self.assertEqual(mock_get_free_floating_ip.call_count, 3)
        _call_mock_get_free_floating_ip = mock_get_free_floating_ip.call_args_list
        self.assertEqual(
            _call_mock_get_free_floating_ip[0][0],
            (
                self.server,
                floating_network,
            ),
        )
        self.assertEqual(
            _call_mock_get_free_floating_ip[1][0],
            (
                self.server,
                floating_network,
            ),
        )
        self.assertEqual(
            _call_mock_get_free_floating_ip[2][0],
            (
                self.server,
                floating_network,
            ),
        )
        self.assertEqual(self.vimconn.neutron.show_floatingip.call_count, 3)
        self.vimconn.nova.servers.get.assert_not_called()
        mock_create_floating_ip.assert_not_called()
        self.assertEqual(mock_assign_floating_ip.call_count, 2)
        _call_mock_assign_floating_ip = mock_assign_floating_ip.call_args_list
        self.assertEqual(
            _call_mock_assign_floating_ip[0][0],
            ("r08b73-o9cc-1a6a-a270-12cc4811bd4u", floating_network),
        )
        self.assertEqual(
            _call_mock_assign_floating_ip[1][0],
            ("y08b73-o9cc-1a6a-a270-12cc4811bd4u", floating_network),
        )

    @patch("time.time")
    @patch("time.sleep")
    @patch.object(vimconnector, "_create_floating_ip")
    @patch.object(vimconnector, "_get_free_floating_ip")
    @patch.object(vimconnector, "_assign_floating_ip")
    def test_prepare_external_network_for_vm_instance_neutron_show_fip_exception_vm_status_in_error(
        self,
        mock_assign_floating_ip,
        mock_get_free_floating_ip,
        mock_create_floating_ip,
        mock_sleep,
        mock_time,
    ):
        """Neutron show floating ip gives exception, exit_on_floating_ip_error set to True,
        VM status is in error."""
        floating_network = {
            "floating_ip": "y08b73-o9cc-1a6a-a270-12cc4811bd4u",
            "vim_id": "608b73-r9cc-5a6a-a270-82cc4811bd4a",
            "exit_on_floating_ip_error": True,
        }
        external_network = [floating_network]
        created_items = {}
        vm_start_time = time_return_value

        mock_time.side_effect = [156570150, 156570800, 156571200]

        self.vimconn.nova.servers.get.return_value.status = "ERROR"
        self.vimconn.neutron.show_floatingip.side_effect = [
            Exception("Floating ip could not be shown.")
        ] * 4
        with self.assertRaises(Exception) as err:
            self.vimconn._prepare_external_network_for_vminstance(
                external_network, self.server, created_items, vm_start_time
            )
            self.assertEqual(
                str(err.exception),
                "Cannot create floating_ip: Exception Floating ip could not be shown.",
            )

        self.assertEqual(mock_get_free_floating_ip.call_count, 4)
        _call_mock_get_free_floating_ip = mock_get_free_floating_ip.call_args_list
        self.assertEqual(
            _call_mock_get_free_floating_ip[0][0],
            (
                self.server,
                floating_network,
            ),
        )
        self.assertEqual(
            _call_mock_get_free_floating_ip[1][0],
            (
                self.server,
                floating_network,
            ),
        )
        self.assertEqual(
            _call_mock_get_free_floating_ip[2][0],
            (
                self.server,
                floating_network,
            ),
        )
        self.assertEqual(
            _call_mock_get_free_floating_ip[3][0],
            (
                self.server,
                floating_network,
            ),
        )

        self.assertEqual(self.vimconn.neutron.show_floatingip.call_count, 4)
        self.vimconn.nova.servers.get.assert_called_with(self.server.id)
        mock_create_floating_ip.assert_not_called()
        mock_assign_floating_ip.assert_not_called()
        mock_time.assert_not_called()
        mock_sleep.assert_not_called()

    @patch("time.time")
    @patch("time.sleep")
    @patch.object(vimconnector, "_create_floating_ip")
    @patch.object(vimconnector, "_get_free_floating_ip")
    @patch.object(vimconnector, "_assign_floating_ip")
    def test_prepare_external_network_for_vm_instance_neutron_show_fip_exception_vm_status_in_active(
        self,
        mock_assign_floating_ip,
        mock_get_free_floating_ip,
        mock_create_floating_ip,
        mock_sleep,
        mock_time,
    ):
        """Neutron show floating ip gives exception, exit_on_floating_ip_error is set to False,
        VM status is in active."""
        floating_network = {
            "floating_ip": "y08b73-o9cc-1a6a-a270-12cc4811bd4u",
            "vim_id": "608b73-r9cc-5a6a-a270-82cc4811bd4a",
            "exit_on_floating_ip_error": False,
        }
        external_network = [floating_network]
        created_items = {}
        vm_start_time = time_return_value

        mock_time.side_effect = [156570150, 156570800, 156571200]

        self.vimconn.nova.servers.get.return_value.status = "ACTIVE"
        self.vimconn.neutron.show_floatingip.side_effect = [
            Exception("Floating ip could not be shown.")
        ] * 4

        self.vimconn._prepare_external_network_for_vminstance(
            external_network, self.server, created_items, vm_start_time
        )
        # self.assertEqual(str(err.exception), "Cannot create floating_ip")

        self.assertEqual(mock_get_free_floating_ip.call_count, 4)
        _call_mock_get_free_floating_ip = mock_get_free_floating_ip.call_args_list
        self.assertEqual(
            _call_mock_get_free_floating_ip[0][0],
            (
                self.server,
                floating_network,
            ),
        )
        self.assertEqual(
            _call_mock_get_free_floating_ip[1][0],
            (
                self.server,
                floating_network,
            ),
        )
        self.assertEqual(
            _call_mock_get_free_floating_ip[2][0],
            (
                self.server,
                floating_network,
            ),
        )
        self.assertEqual(
            _call_mock_get_free_floating_ip[3][0],
            (
                self.server,
                floating_network,
            ),
        )

        self.assertEqual(self.vimconn.neutron.show_floatingip.call_count, 4)
        self.vimconn.nova.servers.get.assert_called_with(self.server.id)
        mock_create_floating_ip.assert_not_called()
        mock_assign_floating_ip.assert_not_called()
        mock_time.assert_not_called()
        mock_sleep.assert_not_called()

    @patch("time.time")
    @patch("time.sleep")
    @patch.object(vimconnector, "_create_floating_ip")
    @patch.object(vimconnector, "_get_free_floating_ip")
    @patch.object(vimconnector, "_assign_floating_ip")
    def test_prepare_external_network_for_vm_instance_neutron_show_fip_exception_exit_on_error(
        self,
        mock_assign_floating_ip,
        mock_get_free_floating_ip,
        mock_create_floating_ip,
        mock_sleep,
        mock_time,
    ):
        """Neutron show floating ip gives exception, but exit_on_floating_ip_error is set to True.
        VM status is not ACTIVE or ERROR, server timeout happened."""
        floating_network = {
            "floating_ip": "y08b73-o9cc-1a6a-a270-12cc4811bd4u",
            "vim_id": "608b73-r9cc-5a6a-a270-82cc4811bd4a",
            "exit_on_floating_ip_error": True,
        }
        external_network = [floating_network]
        created_items = {}
        vm_start_time = time_return_value
        mock_get_free_floating_ip.side_effect = None
        mock_time.side_effect = [156571790, 156571795, 156571800, 156571805]
        self.vimconn.nova.servers.get.return_value.status = "OTHER"
        self.vimconn.neutron.show_floatingip.side_effect = [
            Exception("Floating ip could not be shown.")
        ] * 5

        with self.assertRaises(VimConnException) as err:
            self.vimconn._prepare_external_network_for_vminstance(
                external_network, self.server, created_items, vm_start_time
            )
        self.assertEqual(
            str(err.exception),
            "Cannot create floating_ip: Exception Floating ip could not be shown.",
        )

        self.assertEqual(mock_get_free_floating_ip.call_count, 3)
        _call_mock_get_free_floating_ip = mock_get_free_floating_ip.call_args_list
        self.assertEqual(
            _call_mock_get_free_floating_ip[0][0],
            (
                self.server,
                floating_network,
            ),
        )
        self.assertEqual(
            _call_mock_get_free_floating_ip[1][0],
            (
                self.server,
                floating_network,
            ),
        )
        self.assertEqual(
            _call_mock_get_free_floating_ip[2][0],
            (
                self.server,
                floating_network,
            ),
        )

        self.assertEqual(self.vimconn.neutron.show_floatingip.call_count, 3)
        self.vimconn.nova.servers.get.assert_called_with(self.server.id)
        mock_create_floating_ip.assert_not_called()
        mock_assign_floating_ip.assert_not_called()
        self.assertEqual(mock_time.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)

    @patch("time.time")
    @patch("time.sleep")
    @patch.object(vimconnector, "_create_floating_ip")
    @patch.object(vimconnector, "_get_free_floating_ip")
    @patch.object(vimconnector, "_assign_floating_ip")
    def test_prepare_external_network_for_vm_instance_assign_floating_ip_exception_exit_on_error(
        self,
        mock_assign_floating_ip,
        mock_get_free_floating_ip,
        mock_create_floating_ip,
        mock_sleep,
        mock_time,
    ):
        """Assign floating ip method gives exception, exit_on_floating_ip_error is set to True.
        VM status is in ERROR."""
        floating_network = {
            "floating_ip": "y08b73-o9cc-1a6a-a270-12cc4811bd4u",
            "vim_id": "608b73-r9cc-5a6a-a270-82cc4811bd4a",
            "exit_on_floating_ip_error": True,
        }
        external_network = [floating_network]
        created_items = {}
        vm_start_time = time_return_value

        mock_get_free_floating_ip.side_effect = [
            "y08b73-o9cc-1a6a-a270-12cc4811bd4u"
        ] * 4

        mock_time.side_effect = [156571790, 156571795, 156571800, 156571805]

        mock_assign_floating_ip.side_effect = [
            Exception("Floating ip could not be assigned.")
        ] * 4

        self.vimconn.nova.servers.get.return_value.status = "ERROR"
        self.vimconn.neutron.show_floatingip.side_effect = [
            {"floatingip": {"port_id": ""}}
        ] * 4

        with self.assertRaises(VimConnException) as err:
            self.vimconn._prepare_external_network_for_vminstance(
                external_network, self.server, created_items, vm_start_time
            )
        self.assertEqual(
            str(err.exception),
            "Cannot create floating_ip: Exception Floating ip could not be assigned.",
        )

        self.assertEqual(mock_get_free_floating_ip.call_count, 4)
        _call_mock_get_free_floating_ip = mock_get_free_floating_ip.call_args_list
        self.assertEqual(
            _call_mock_get_free_floating_ip[0][0],
            (
                self.server,
                floating_network,
            ),
        )
        self.assertEqual(
            _call_mock_get_free_floating_ip[1][0],
            (
                self.server,
                floating_network,
            ),
        )
        self.assertEqual(
            _call_mock_get_free_floating_ip[2][0],
            (
                self.server,
                floating_network,
            ),
        )

        self.assertEqual(self.vimconn.neutron.show_floatingip.call_count, 4)
        self.vimconn.neutron.show_floatingip.assert_called_with(
            "y08b73-o9cc-1a6a-a270-12cc4811bd4u"
        )
        self.assertEqual(self.vimconn.nova.servers.get.call_count, 4)
        self.vimconn.nova.servers.get.assert_called_with(self.server.id)
        mock_time.assert_not_called()
        mock_sleep.assert_not_called()
        mock_create_floating_ip.assert_not_called()

    @patch("time.time")
    @patch("time.sleep")
    @patch.object(vimconnector, "_create_floating_ip")
    @patch.object(vimconnector, "_get_free_floating_ip")
    @patch.object(vimconnector, "_assign_floating_ip")
    def test_prepare_external_network_for_vm_instance_empty_external_network_list(
        self,
        mock_assign_floating_ip,
        mock_get_free_floating_ip,
        mock_create_floating_ip,
        mock_sleep,
        mock_time,
    ):
        """External network list is empty."""
        external_network = []
        created_items = {}
        vm_start_time = time_return_value

        self.vimconn._prepare_external_network_for_vminstance(
            external_network, self.server, created_items, vm_start_time
        )
        mock_create_floating_ip.assert_not_called()
        mock_time.assert_not_called()
        mock_sleep.assert_not_called()
        mock_assign_floating_ip.assert_not_called()
        mock_get_free_floating_ip.assert_not_called()
        self.vimconn.neutron.show.show_floatingip.assert_not_called()
        self.vimconn.nova.servers.get.assert_not_called()

    @patch.object(vimconnector, "_vimconnector__wait_for_vm")
    def test_update_port_security_for_vm_instance(self, mock_wait_for_vm):
        """no_secured_ports has port and the port has allow-address-pairs."""
        no_secured_ports = [(port2_id, "allow-address-pairs")]

        self.vimconn._update_port_security_for_vminstance(no_secured_ports, self.server)

        mock_wait_for_vm.assert_called_once_with(self.server.id, "ACTIVE")

        self.vimconn.neutron.update_port.assert_called_once_with(
            port2_id,
            {"port": {"allowed_address_pairs": [{"ip_address": "0.0.0.0/0"}]}},
        )

    @patch.object(vimconnector, "_vimconnector__wait_for_vm")
    def test_update_port_security_for_vm_instance_no_allowed_address_pairs(
        self, mock_wait_for_vm
    ):
        """no_secured_ports has port and the port does not have allow-address-pairs."""
        no_secured_ports = [(port2_id, "something")]

        self.vimconn._update_port_security_for_vminstance(no_secured_ports, self.server)

        mock_wait_for_vm.assert_called_once_with(self.server.id, "ACTIVE")

        self.vimconn.neutron.update_port.assert_called_once_with(
            port2_id,
            {"port": {"port_security_enabled": False, "security_groups": None}},
        )

    @patch.object(vimconnector, "_vimconnector__wait_for_vm")
    def test_update_port_security_for_vm_instance_wait_for_vm_raise_exception(
        self, mock_wait_for_vm
    ):
        """__wait_for_vm raises timeout exception."""
        no_secured_ports = [(port2_id, "something")]

        mock_wait_for_vm.side_effect = VimConnException("Timeout waiting for instance.")

        with self.assertRaises(VimConnException) as err:
            self.vimconn._update_port_security_for_vminstance(
                no_secured_ports, self.server
            )
        self.assertEqual(str(err.exception), "Timeout waiting for instance.")

        mock_wait_for_vm.assert_called_once_with(self.server.id, "ACTIVE")

        self.vimconn.neutron.update_port.assert_not_called()

    @patch.object(vimconnector, "_vimconnector__wait_for_vm")
    def test_update_port_security_for_vm_instance_neutron_update_port_raise_exception(
        self, mock_wait_for_vm
    ):
        """neutron_update_port method raises exception."""
        no_secured_ports = [(port2_id, "something")]

        self.vimconn.neutron.update_port.side_effect = Exception(
            "Port security could not be updated."
        )

        with self.assertRaises(VimConnException) as err:
            self.vimconn._update_port_security_for_vminstance(
                no_secured_ports, self.server
            )
        self.assertEqual(
            str(err.exception),
            "It was not possible to disable port security for port 17472685-f67f-49fd-8722-eabb7692fc22",
        )
        mock_wait_for_vm.assert_called_once_with(self.server.id, "ACTIVE")

        self.vimconn.neutron.update_port.assert_called_once_with(
            port2_id,
            {"port": {"port_security_enabled": False, "security_groups": None}},
        )

    @patch.object(vimconnector, "_vimconnector__wait_for_vm")
    def test_update_port_security_for_vm_instance_empty_port_list(
        self, mock_wait_for_vm
    ):
        """no_secured_ports list does not have any ports."""
        no_secured_ports = []

        self.vimconn._update_port_security_for_vminstance(no_secured_ports, self.server)

        mock_wait_for_vm.assert_not_called()

        self.vimconn.neutron.update_port.assert_not_called()

    @patch("time.time")
    @patch.object(vimconnector, "remove_keep_tag_from_persistent_volumes")
    @patch.object(vimconnector, "_reload_connection")
    @patch.object(vimconnector, "_prepare_network_for_vminstance")
    @patch.object(vimconnector, "_create_user_data")
    @patch.object(vimconnector, "_get_vm_availability_zone")
    @patch.object(vimconnector, "_prepare_disk_for_vminstance")
    @patch.object(vimconnector, "_update_port_security_for_vminstance")
    @patch.object(vimconnector, "_prepare_external_network_for_vminstance")
    @patch.object(vimconnector, "delete_vminstance")
    @patch.object(vimconnector, "_format_exception")
    def test_new_vm_instance(
        self,
        mock_format_exception,
        mock_delete_vm_instance,
        mock_prepare_external_network,
        mock_update_port_security,
        mock_prepare_disk_for_vm_instance,
        mock_get_vm_availability_zone,
        mock_create_user_data,
        mock_prepare_network_for_vm_instance,
        mock_reload_connection,
        mock_remove_keep_flag_from_persistent_volumes,
        mock_time,
    ):
        """New VM instance creation is successful."""

        mock_create_user_data.return_value = True, "userdata"

        mock_get_vm_availability_zone.return_value = "nova"

        self.vimconn.nova.servers.create.return_value = self.server

        mock_time.return_value = time_return_value

        expected_result = self.server.id, {}

        result = self.vimconn.new_vminstance(
            name,
            description,
            start,
            image_id,
            flavor_id,
            affinity_group_list,
            net_list,
            cloud_config,
            disk_list2,
            availability_zone_index,
            availability_zone_list,
            security_group_name,
        )
        self.assertEqual(result, expected_result)

        mock_reload_connection.assert_called_once()
        mock_prepare_network_for_vm_instance.assert_called_once_with(
            name=name,
            net_list=net_list,
            created_items={},
            net_list_vim=[],
            external_network=[],
            no_secured_ports=[],
            security_group_name=security_group_name,
        )
        mock_create_user_data.assert_called_once_with(cloud_config)
        mock_get_vm_availability_zone.assert_called_once_with(
            availability_zone_index, availability_zone_list
        )
        mock_prepare_disk_for_vm_instance.assert_called_once_with(
            name=name,
            existing_vim_volumes=[],
            created_items={},
            storage_av_zone="nova",
            block_device_mapping={},
            disk_list=disk_list2,
        )
        self.vimconn.nova.servers.create.assert_called_once_with(
            name=name,
            image=image_id,
            flavor=flavor_id,
            nics=[],
            security_groups="default",
            availability_zone="nova",
            key_name="my_keypair",
            userdata="userdata",
            config_drive=True,
            block_device_mapping={},
            scheduler_hints={},
        )
        mock_time.assert_called_once()
        mock_update_port_security.assert_called_once_with([], self.server)
        mock_prepare_external_network.assert_called_once_with(
            external_network=[],
            server=self.server,
            created_items={},
            vm_start_time=time_return_value,
        )
        mock_remove_keep_flag_from_persistent_volumes.assert_not_called()
        mock_delete_vm_instance.assert_not_called()
        mock_format_exception.assert_not_called()

    @patch("time.time")
    @patch.object(vimconnector, "remove_keep_tag_from_persistent_volumes")
    @patch.object(vimconnector, "_reload_connection")
    @patch.object(vimconnector, "_prepare_network_for_vminstance")
    @patch.object(vimconnector, "_create_user_data")
    @patch.object(vimconnector, "_get_vm_availability_zone")
    @patch.object(vimconnector, "_prepare_disk_for_vminstance")
    @patch.object(vimconnector, "_update_port_security_for_vminstance")
    @patch.object(vimconnector, "_prepare_external_network_for_vminstance")
    @patch.object(vimconnector, "delete_vminstance")
    @patch.object(vimconnector, "_format_exception")
    def test_new_vm_instance_create_user_data_fails(
        self,
        mock_format_exception,
        mock_delete_vm_instance,
        mock_prepare_external_network,
        mock_update_port_security,
        mock_prepare_disk_for_vm_instance,
        mock_get_vm_availability_zone,
        mock_create_user_data,
        mock_prepare_network_for_vm_instance,
        mock_reload_connection,
        mock_remove_keep_flag_from_persistent_volumes,
        mock_time,
    ):
        """New VM instance creation failed because of user data creation failure."""

        mock_create_user_data.side_effect = Exception(
            "User data could not be retrieved."
        )

        mock_get_vm_availability_zone.return_value = "nova"

        mock_remove_keep_flag_from_persistent_volumes.return_value = {}

        self.vimconn.nova.servers.create.return_value = self.server

        mock_time.return_value = time_return_value

        self.vimconn.new_vminstance(
            name,
            description,
            start,
            image_id,
            flavor_id,
            affinity_group_list,
            net_list,
            cloud_config,
            disk_list,
            availability_zone_index,
            availability_zone_list,
            security_group_name,
        )

        mock_reload_connection.assert_called_once()
        mock_prepare_network_for_vm_instance.assert_called_once_with(
            name=name,
            net_list=net_list,
            created_items={},
            net_list_vim=[],
            external_network=[],
            no_secured_ports=[],
            security_group_name=security_group_name,
        )
        mock_create_user_data.assert_called_once_with(cloud_config)
        mock_get_vm_availability_zone.assert_not_called()
        mock_prepare_disk_for_vm_instance.assert_not_called()
        self.vimconn.nova.servers.create.assert_not_called()
        mock_time.assert_not_called()
        mock_update_port_security.assert_not_called()
        mock_prepare_external_network.assert_not_called()
        mock_remove_keep_flag_from_persistent_volumes.assert_called_once_with({})
        mock_delete_vm_instance.assert_called_once_with(None, {})
        mock_format_exception.assert_called_once()
        arg = mock_format_exception.call_args[0][0]
        self.assertEqual(str(arg), "User data could not be retrieved.")

    @patch("time.time")
    @patch.object(vimconnector, "remove_keep_tag_from_persistent_volumes")
    @patch.object(vimconnector, "_reload_connection")
    @patch.object(vimconnector, "_prepare_network_for_vminstance")
    @patch.object(vimconnector, "_create_user_data")
    @patch.object(vimconnector, "_get_vm_availability_zone")
    @patch.object(vimconnector, "_prepare_disk_for_vminstance")
    @patch.object(vimconnector, "_update_port_security_for_vminstance")
    @patch.object(vimconnector, "_prepare_external_network_for_vminstance")
    @patch.object(vimconnector, "delete_vminstance")
    @patch.object(vimconnector, "_format_exception")
    def test_new_vm_instance_external_network_exception(
        self,
        mock_format_exception,
        mock_delete_vm_instance,
        mock_prepare_external_network,
        mock_update_port_security,
        mock_prepare_disk_for_vm_instance,
        mock_get_vm_availability_zone,
        mock_create_user_data,
        mock_prepare_network_for_vm_instance,
        mock_reload_connection,
        mock_remove_keep_flag_from_persistent_volumes,
        mock_time,
    ):
        """New VM instance creation, external network connection has failed as floating
        ip could not be created."""

        mock_create_user_data.return_value = True, "userdata"

        mock_get_vm_availability_zone.return_value = "nova"

        self.vimconn.nova.servers.create.return_value = self.server

        mock_time.return_value = time_return_value

        mock_remove_keep_flag_from_persistent_volumes.return_value = {}

        mock_prepare_external_network.side_effect = VimConnException(
            "Can not create floating ip."
        )

        self.vimconn.new_vminstance(
            name,
            description,
            start,
            image_id,
            flavor_id,
            affinity_group_list,
            net_list,
            cloud_config,
            disk_list2,
            availability_zone_index,
            availability_zone_list,
        )

        mock_reload_connection.assert_called_once()
        mock_prepare_network_for_vm_instance.assert_called_once_with(
            name=name,
            net_list=net_list,
            created_items={},
            net_list_vim=[],
            external_network=[],
            no_secured_ports=[],
            security_group_name=security_group_name,
        )
        mock_create_user_data.assert_called_once_with(cloud_config)
        mock_get_vm_availability_zone.assert_called_once_with(
            availability_zone_index, availability_zone_list
        )
        mock_prepare_disk_for_vm_instance.assert_called_once_with(
            name=name,
            existing_vim_volumes=[],
            created_items={},
            storage_av_zone="nova",
            block_device_mapping={},
            disk_list=disk_list2,
        )
        self.vimconn.nova.servers.create.assert_called_once_with(
            name=name,
            image=image_id,
            flavor=flavor_id,
            nics=[],
            security_groups="default",
            availability_zone="nova",
            key_name="my_keypair",
            userdata="userdata",
            config_drive=True,
            block_device_mapping={},
            scheduler_hints={},
        )
        mock_time.assert_called_once()
        mock_update_port_security.assert_called_once_with([], self.server)
        mock_prepare_external_network.assert_called_once_with(
            external_network=[],
            server=self.server,
            created_items={},
            vm_start_time=time_return_value,
        )
        mock_remove_keep_flag_from_persistent_volumes.assert_called_once_with({})
        mock_delete_vm_instance.assert_called_once_with(self.server.id, {})
        mock_format_exception.assert_called_once()
        arg = mock_format_exception.call_args[0][0]
        self.assertEqual(str(arg), "Can not create floating ip.")

    @patch("time.time")
    @patch.object(vimconnector, "remove_keep_tag_from_persistent_volumes")
    @patch.object(vimconnector, "_reload_connection")
    @patch.object(vimconnector, "_prepare_network_for_vminstance")
    @patch.object(vimconnector, "_create_user_data")
    @patch.object(vimconnector, "_get_vm_availability_zone")
    @patch.object(vimconnector, "_prepare_disk_for_vminstance")
    @patch.object(vimconnector, "_update_port_security_for_vminstance")
    @patch.object(vimconnector, "_prepare_external_network_for_vminstance")
    @patch.object(vimconnector, "delete_vminstance")
    @patch.object(vimconnector, "_format_exception")
    def test_new_vm_instance_with_affinity_group(
        self,
        mock_format_exception,
        mock_delete_vm_instance,
        mock_prepare_external_network,
        mock_update_port_security,
        mock_prepare_disk_for_vm_instance,
        mock_get_vm_availability_zone,
        mock_create_user_data,
        mock_prepare_network_for_vm_instance,
        mock_reload_connection,
        mock_remove_keep_flag_from_persistent_volumes,
        mock_time,
    ):
        """New VM creation with affinity group."""
        affinity_group_list = [
            {"affinity_group_id": "38b73-e9cc-5a6a-t270-82cc4811bd4a"}
        ]
        mock_create_user_data.return_value = True, "userdata"
        mock_get_vm_availability_zone.return_value = "nova"
        self.vimconn.nova.servers.create.return_value = self.server
        mock_time.return_value = time_return_value
        expected_result = self.server.id, {}

        result = self.vimconn.new_vminstance(
            name,
            description,
            start,
            image_id,
            flavor_id,
            affinity_group_list,
            net_list,
            cloud_config,
            disk_list2,
            availability_zone_index,
            availability_zone_list,
            security_group_name,
        )
        self.assertEqual(result, expected_result)

        mock_reload_connection.assert_called_once()
        mock_prepare_network_for_vm_instance.assert_called_once_with(
            name=name,
            net_list=net_list,
            created_items={},
            net_list_vim=[],
            external_network=[],
            no_secured_ports=[],
            security_group_name=security_group_name,
        )
        mock_create_user_data.assert_called_once_with(cloud_config)
        mock_get_vm_availability_zone.assert_called_once_with(
            availability_zone_index, availability_zone_list
        )
        mock_prepare_disk_for_vm_instance.assert_called_once_with(
            name=name,
            existing_vim_volumes=[],
            created_items={},
            storage_av_zone="nova",
            block_device_mapping={},
            disk_list=disk_list2,
        )
        self.vimconn.nova.servers.create.assert_called_once_with(
            name=name,
            image=image_id,
            flavor=flavor_id,
            nics=[],
            security_groups="default",
            availability_zone="nova",
            key_name="my_keypair",
            userdata="userdata",
            config_drive=True,
            block_device_mapping={},
            scheduler_hints={"group": "38b73-e9cc-5a6a-t270-82cc4811bd4a"},
        )
        mock_time.assert_called_once()
        mock_update_port_security.assert_called_once_with([], self.server)
        mock_prepare_external_network.assert_called_once_with(
            external_network=[],
            server=self.server,
            created_items={},
            vm_start_time=time_return_value,
        )
        mock_remove_keep_flag_from_persistent_volumes.assert_not_called()
        mock_delete_vm_instance.assert_not_called()
        mock_format_exception.assert_not_called()

    @patch("time.time")
    @patch.object(vimconnector, "remove_keep_tag_from_persistent_volumes")
    @patch.object(vimconnector, "_reload_connection")
    @patch.object(vimconnector, "_prepare_network_for_vminstance")
    @patch.object(vimconnector, "_create_user_data")
    @patch.object(vimconnector, "_get_vm_availability_zone")
    @patch.object(vimconnector, "_prepare_disk_for_vminstance")
    @patch.object(vimconnector, "_update_port_security_for_vminstance")
    @patch.object(vimconnector, "_prepare_external_network_for_vminstance")
    @patch.object(vimconnector, "delete_vminstance")
    @patch.object(vimconnector, "_format_exception")
    def test_new_vm_instance_nova_server_create_failed(
        self,
        mock_format_exception,
        mock_delete_vm_instance,
        mock_prepare_external_network,
        mock_update_port_security,
        mock_prepare_disk_for_vm_instance,
        mock_get_vm_availability_zone,
        mock_create_user_data,
        mock_prepare_network_for_vm_instance,
        mock_reload_connection,
        mock_remove_keep_flag_from_persistent_volumes,
        mock_time,
    ):
        """New VM(server) creation failed."""

        mock_create_user_data.return_value = True, "userdata"

        mock_get_vm_availability_zone.return_value = "nova"

        self.vimconn.nova.servers.create.side_effect = Exception(
            "Server could not be created."
        )

        mock_time.return_value = time_return_value

        mock_remove_keep_flag_from_persistent_volumes.return_value = {}

        self.vimconn.new_vminstance(
            name,
            description,
            start,
            image_id,
            flavor_id,
            affinity_group_list,
            net_list,
            cloud_config,
            disk_list2,
            availability_zone_index,
            availability_zone_list,
            security_group_name,
        )

        mock_reload_connection.assert_called_once()
        mock_prepare_network_for_vm_instance.assert_called_once_with(
            name=name,
            net_list=net_list,
            created_items={},
            net_list_vim=[],
            external_network=[],
            no_secured_ports=[],
            security_group_name=security_group_name,
        )
        mock_create_user_data.assert_called_once_with(cloud_config)
        mock_get_vm_availability_zone.assert_called_once_with(
            availability_zone_index, availability_zone_list
        )
        mock_prepare_disk_for_vm_instance.assert_called_once_with(
            name=name,
            existing_vim_volumes=[],
            created_items={},
            storage_av_zone="nova",
            block_device_mapping={},
            disk_list=disk_list2,
        )

        self.vimconn.nova.servers.create.assert_called_once_with(
            name=name,
            image=image_id,
            flavor=flavor_id,
            nics=[],
            security_groups="default",
            availability_zone="nova",
            key_name="my_keypair",
            userdata="userdata",
            config_drive=True,
            block_device_mapping={},
            scheduler_hints={},
        )
        mock_time.assert_not_called()
        mock_update_port_security.assert_not_called()
        mock_prepare_external_network.assert_not_called()
        mock_remove_keep_flag_from_persistent_volumes.assert_called_once_with({})
        mock_delete_vm_instance.assert_called_once_with(None, {})
        mock_format_exception.assert_called_once()
        arg = mock_format_exception.call_args[0][0]
        self.assertEqual(str(arg), "Server could not be created.")

    @patch("time.time")
    @patch.object(vimconnector, "remove_keep_tag_from_persistent_volumes")
    @patch.object(vimconnector, "_reload_connection")
    @patch.object(vimconnector, "_prepare_network_for_vminstance")
    @patch.object(vimconnector, "_create_user_data")
    @patch.object(vimconnector, "_get_vm_availability_zone")
    @patch.object(vimconnector, "_prepare_disk_for_vminstance")
    @patch.object(vimconnector, "_update_port_security_for_vminstance")
    @patch.object(vimconnector, "_prepare_external_network_for_vminstance")
    @patch.object(vimconnector, "delete_vminstance")
    @patch.object(vimconnector, "_format_exception")
    def test_new_vm_instance_connection_exception(
        self,
        mock_format_exception,
        mock_delete_vm_instance,
        mock_prepare_external_network,
        mock_update_port_security,
        mock_prepare_disk_for_vm_instance,
        mock_get_vm_availability_zone,
        mock_create_user_data,
        mock_prepare_network_for_vm_instance,
        mock_reload_connection,
        mock_remove_keep_flag_from_persistent_volumes,
        mock_time,
    ):
        """Connection to Cloud API has failed."""
        mock_reload_connection.side_effect = Exception("Can not connect to Cloud APIs.")
        mock_create_user_data.return_value = True, "userdata"
        mock_get_vm_availability_zone.return_value = "nova"
        self.vimconn.nova.servers.create.return_value = self.server
        mock_time.return_value = time_return_value
        mock_remove_keep_flag_from_persistent_volumes.return_value = {}

        self.vimconn.new_vminstance(
            name,
            description,
            start,
            image_id,
            flavor_id,
            affinity_group_list,
            net_list,
            cloud_config,
            disk_list,
            availability_zone_index,
            availability_zone_list,
        )
        mock_format_exception.assert_called_once()
        arg = mock_format_exception.call_args[0][0]
        self.assertEqual(str(arg), "Can not connect to Cloud APIs.")
        mock_reload_connection.assert_called_once()
        mock_prepare_network_for_vm_instance.assert_not_called()
        mock_create_user_data.assert_not_called()
        mock_get_vm_availability_zone.assert_not_called()
        mock_prepare_disk_for_vm_instance.assert_not_called()
        self.vimconn.nova.servers.create.assert_not_called()
        mock_time.assert_not_called()
        mock_update_port_security.assert_not_called()
        mock_prepare_external_network.assert_not_called()
        mock_remove_keep_flag_from_persistent_volumes.assert_called_once_with({})
        mock_delete_vm_instance.assert_called_once_with(None, {})

    @patch.object(vimconnector, "_delete_ports_by_id_wth_neutron")
    def test_delete_vm_ports_attached_to_network_empty_created_items(
        self, mock_delete_ports_by_id_wth_neutron
    ):
        """Created_items is emtpty."""
        created_items = {}
        self.vimconn._delete_vm_ports_attached_to_network(created_items)
        self.vimconn.neutron.list_ports.assert_not_called()
        self.vimconn.neutron.delete_port.assert_not_called()
        mock_delete_ports_by_id_wth_neutron.assert_not_called()

    @patch.object(vimconnector, "_delete_ports_by_id_wth_neutron")
    def test_delete_vm_ports_attached_to_network(
        self, mock_delete_ports_by_id_wth_neutron
    ):
        created_items = {
            "floating_ip:308b73-t9cc-1a6a-a270-12cc4811bd4a": True,
            f"volume:{volume_id2}": True,
            f"volume:{volume_id}": True,
            f"port:{port_id}": True,
        }
        self.vimconn._delete_vm_ports_attached_to_network(created_items)
        mock_delete_ports_by_id_wth_neutron.assert_called_once_with(f"{port_id}")
        self.vimconn.logger.error.assert_not_called()

    @patch.object(vimconnector, "_delete_ports_by_id_wth_neutron")
    def test_delete_vm_ports_attached_to_network_wthout_port(
        self, mock_delete_ports_by_id_wth_neutron
    ):
        """Created_items does not have port."""
        created_items = {
            f"floating_ip:{floating_network_vim_id}": True,
            f"volume:{volume_id2}": True,
            f"volume:{volume_id}": True,
        }
        self.vimconn._delete_vm_ports_attached_to_network(created_items)
        mock_delete_ports_by_id_wth_neutron.assert_not_called()
        self.vimconn.logger.error.assert_not_called()

    @patch.object(vimconnector, "_delete_ports_by_id_wth_neutron")
    def test_delete_vm_ports_attached_to_network_delete_port_raise_vimconnexception(
        self, mock_delete_ports_by_id_wth_neutron
    ):
        """_delete_ports_by_id_wth_neutron raises vimconnexception."""
        created_items = deepcopy(created_items_all_true)
        mock_delete_ports_by_id_wth_neutron.side_effect = VimConnException(
            "Can not delete port"
        )
        self.vimconn._delete_vm_ports_attached_to_network(created_items)
        mock_delete_ports_by_id_wth_neutron.assert_called_once_with(f"{port_id}")
        self.vimconn.logger.error.assert_called_once_with(
            "Error deleting port: VimConnException: Can not delete port"
        )

    @patch.object(vimconnector, "_delete_ports_by_id_wth_neutron")
    def test_delete_vm_ports_attached_to_network_delete_port_raise_nvexception(
        self, mock_delete_ports_by_id_wth_neutron
    ):
        """_delete_ports_by_id_wth_neutron raises nvExceptions.ClientException."""
        created_items = deepcopy(created_items_all_true)
        mock_delete_ports_by_id_wth_neutron.side_effect = nvExceptions.ClientException(
            "Connection aborted."
        )
        self.vimconn._delete_vm_ports_attached_to_network(created_items)
        mock_delete_ports_by_id_wth_neutron.assert_called_once_with(f"{port_id}")
        self.vimconn.logger.error.assert_called_once_with(
            "Error deleting port: ClientException: Unknown Error (HTTP Connection aborted.)"
        )

    @patch.object(vimconnector, "_delete_ports_by_id_wth_neutron")
    def test_delete_vm_ports_attached_to_network_delete_port_invalid_port_item(
        self, mock_delete_ports_by_id_wth_neutron
    ):
        """port item is invalid."""
        created_items = {
            f"floating_ip:{floating_network_vim_id}": True,
            f"volume:{volume_id2}": True,
            f"volume:{volume_id}": True,
            f"port:{port_id}:": True,
        }
        mock_delete_ports_by_id_wth_neutron.side_effect = VimConnException(
            "Port is not valid."
        )
        self.vimconn._delete_vm_ports_attached_to_network(created_items)
        mock_delete_ports_by_id_wth_neutron.assert_called_once_with(f"{port_id}:")
        self.vimconn.logger.error.assert_called_once_with(
            "Error deleting port: VimConnException: Port is not valid."
        )

    @patch.object(vimconnector, "_delete_ports_by_id_wth_neutron")
    def test_delete_vm_ports_attached_to_network_delete_port_already_deleted(
        self, mock_delete_ports_by_id_wth_neutron
    ):
        """port is already deleted."""
        created_items = {
            f"floating_ip:{floating_network_vim_id}": True,
            f"volume:{volume_id2}": True,
            f"volume:{volume_id}": None,
            f"port:{port_id}": None,
        }
        self.vimconn._delete_vm_ports_attached_to_network(created_items)
        mock_delete_ports_by_id_wth_neutron.assert_not_called()
        self.vimconn.logger.error.assert_not_called()

    def test_delete_floating_ip_by_id(self):
        created_items = {
            f"floating_ip:{floating_network_vim_id}": True,
            f"port:{port_id}": True,
        }
        expected_created_items = {
            f"floating_ip:{floating_network_vim_id}": None,
            f"port:{port_id}": True,
        }
        k_id = floating_network_vim_id
        k = f"floating_ip:{floating_network_vim_id}"
        self.vimconn._delete_floating_ip_by_id(k, k_id, created_items)
        self.vimconn.neutron.delete_floatingip.assert_called_once_with(k_id)
        self.assertEqual(created_items, expected_created_items)

    def test_delete_floating_ip_by_id_floating_ip_already_deleted(self):
        """floating ip is already deleted."""
        created_items = {
            f"floating_ip:{floating_network_vim_id}": None,
            f"port:{port_id}": True,
        }
        k_id = floating_network_vim_id
        k = f"floating_ip:{floating_network_vim_id}"
        self.vimconn._delete_floating_ip_by_id(k, k_id, created_items)
        self.vimconn.neutron.delete_floatingip.assert_called_once_with(k_id)
        self.assertEqual(
            created_items,
            {
                f"floating_ip:{floating_network_vim_id}": None,
                f"port:{port_id}": True,
            },
        )

    def test_delete_floating_ip_by_id__delete_floating_ip_raises_client_exception__operation_is_successful(
        self,
    ):
        """netron delete floating ip raises nvExceptions.ClientException."""
        created_items = {
            f"floating_ip:{floating_network_vim_id}": True,
            f"port:{port_id}": True,
        }
        k_id = floating_network_vim_id
        k = f"floating_ip:{floating_network_vim_id}"
        self.vimconn.neutron.delete_floatingip.side_effect = (
            nvExceptions.ClientException("Client exception occurred.")
        )
        self.vimconn._delete_floating_ip_by_id(k, k_id, created_items)
        self.vimconn.neutron.delete_floatingip.assert_called_once_with(k_id)
        self.assertEqual(
            created_items,
            {
                f"floating_ip:{floating_network_vim_id}": True,
                f"port:{port_id}": True,
            },
        )
        self.vimconn.logger.error.assert_called_once_with(
            "Error deleting floating ip: ClientException: Unknown Error (HTTP Client exception occurred.)"
        )

    def test_delete_floating_ip_by_id__delete_floating_ip_raises_connection_error__operation_fails(
        self,
    ):
        """netron delete floating ip raises nvExceptions.ClientException."""
        created_items = {
            f"floating_ip:{floating_network_vim_id}": True,
            f"port:{port_id}": True,
        }
        k_id = floating_network_vim_id
        k = f"floating_ip:{floating_network_vim_id}"
        self.vimconn.neutron.delete_floatingip.side_effect = ConnectionError(
            "Connection exception occurred."
        )
        with self.assertRaises(VimConnConnectionException):
            self.vimconn._delete_floating_ip_by_id(k, k_id, created_items)
        self.vimconn.neutron.delete_floatingip.assert_called_once_with(k_id)
        self.assertEqual(
            created_items,
            {
                f"floating_ip:{floating_network_vim_id}": True,
                f"port:{port_id}": True,
            },
        )
        self.vimconn.logger.error.assert_called_once_with(
            "Error deleting floating ip: ConnectionError: Connection exception occurred."
        )

    def test_delete_floating_ip_by_id_floating_ip_raises_vimconn_not_found_exception__operation_is_successful(
        self,
    ):
        """netron delete floating ip raises VimConnNotFoundException."""
        created_items = {
            f"floating_ip:{floating_network_vim_id}": True,
            f"port:{port_id}": True,
        }
        k_id = floating_network_vim_id
        k = f"floating_ip:{floating_network_vim_id}"
        self.vimconn.neutron.delete_floatingip.side_effect = VimConnNotFoundException(
            "Port id could not found."
        )
        self.vimconn._delete_floating_ip_by_id(k, k_id, created_items)
        self.vimconn.neutron.delete_floatingip.assert_called_once_with(k_id)
        self.assertEqual(
            created_items,
            {
                f"floating_ip:{floating_network_vim_id}": True,
                f"port:{port_id}": True,
            },
        )
        self.vimconn.logger.error.assert_called_once_with(
            "Error deleting floating ip: VimConnNotFoundException: Port id could not found."
        )

    def test_delete_floating_ip_by_id_floating_ip_invalid_k_item(self):
        """invalid floating ip item."""
        created_items = {
            f"floating_ip:{floating_network_vim_id}": True,
            f"port:{port_id}": True,
        }
        expected_created_items = {
            f"floating_ip:{floating_network_vim_id}::": None,
            f"floating_ip:{floating_network_vim_id}": True,
            f"port:{port_id}": True,
        }
        k_id = floating_network_vim_id
        k = f"floating_ip:{floating_network_vim_id}::"
        self.vimconn._delete_floating_ip_by_id(k, k_id, created_items)
        self.vimconn.neutron.delete_floatingip.assert_called_once_with(k_id)
        self.assertEqual(created_items, expected_created_items)

    def test_delete_volumes_by_id_with_cinder_volume_status_available(self):
        """volume status is available."""
        created_items = {
            f"floating_ip:{floating_network_vim_id}": True,
            f"volume:{volume_id2}": True,
            f"volume:{volume_id}": True,
            f"port:{port_id}": None,
        }
        expected_created_items = {
            f"floating_ip:{floating_network_vim_id}": True,
            f"volume:{volume_id2}": True,
            f"volume:{volume_id}": None,
            f"port:{port_id}": None,
        }
        volumes_to_hold = []
        k = f"volume:{volume_id}"
        k_id = volume_id
        self.vimconn.cinder.volumes.get.return_value.status = "available"
        result = self.vimconn._delete_volumes_by_id_wth_cinder(
            k, k_id, volumes_to_hold, created_items
        )
        self.assertEqual(result, None)
        self.vimconn.cinder.volumes.get.assert_called_once_with(k_id)
        self.vimconn.cinder.volumes.delete.assert_called_once_with(k_id)
        self.vimconn.logger.error.assert_not_called()
        self.assertEqual(created_items, expected_created_items)

    def test_delete_volumes_by_id_with_cinder_volume_already_deleted(self):
        """volume is already deleted."""
        created_items = {
            f"floating_ip:{floating_network_vim_id}": True,
            f"volume:{volume_id2}": True,
            f"volume:{volume_id}": None,
            f"port:{port_id}": None,
        }
        expected_created_items = {
            f"floating_ip:{floating_network_vim_id}": True,
            f"volume:{volume_id2}": True,
            f"volume:{volume_id}": None,
            f"port:{port_id}": None,
        }
        volumes_to_hold = []
        k = f"volume:{volume_id}"
        k_id = volume_id
        self.vimconn.cinder.volumes.get.return_value.status = "available"
        result = self.vimconn._delete_volumes_by_id_wth_cinder(
            k, k_id, volumes_to_hold, created_items
        )
        self.assertEqual(result, None)
        self.vimconn.cinder.volumes.get.assert_called_once_with(k_id)
        self.vimconn.cinder.volumes.delete.assert_called_once_with(k_id)
        self.vimconn.logger.error.assert_not_called()
        self.assertEqual(created_items, expected_created_items)

    def test_delete_shared_volumes(self):
        """cinder delete shared volumes"""
        shared_volume_vim_id = volume_id4
        self.vimconn.cinder.volumes.get.return_value.status = "available"
        self.vimconn.delete_shared_volumes(shared_volume_vim_id)
        self.vimconn.cinder.volumes.get.assert_called_once_with(shared_volume_vim_id)
        self.vimconn.cinder.volumes.delete.assert_called_once_with(shared_volume_vim_id)
        self.vimconn.logger.error.assert_not_called()

    def test_delete_volumes_by_id_with_cinder_get_volume_raise_exception(self):
        """cinder get volume raises exception."""
        created_items = {
            f"floating_ip:{floating_network_vim_id}": True,
            f"volume:{volume_id2}": True,
            f"volume:{volume_id}": True,
            f"port:{port_id}": None,
        }
        expected_created_items = {
            f"floating_ip:{floating_network_vim_id}": True,
            f"volume:{volume_id2}": True,
            f"volume:{volume_id}": True,
            f"port:{port_id}": None,
        }
        volumes_to_hold = []
        k = f"volume:{volume_id}"
        k_id = volume_id
        self.vimconn.cinder.volumes.get.side_effect = Exception(
            "Can not get volume status."
        )
        result = self.vimconn._delete_volumes_by_id_wth_cinder(
            k, k_id, volumes_to_hold, created_items
        )
        self.assertEqual(result, None)
        self.vimconn.cinder.volumes.get.assert_called_once_with(k_id)
        self.vimconn.cinder.volumes.delete.assert_not_called()
        self.vimconn.logger.error.assert_called_once_with(
            "Error deleting volume: Exception: Can not get volume status."
        )
        self.assertEqual(created_items, expected_created_items)

    def test_delete_volumes_by_id_with_cinder__delete_volume_raise_client_exception__exception_is_not_raised(
        self,
    ):
        """cinder delete volume raises exception."""
        created_items = {
            f"floating_ip:{floating_network_vim_id}": True,
            f"volume:{volume_id2}": True,
            f"volume:{volume_id}": True,
            f"port:{port_id}": None,
        }
        expected_created_items = {
            f"floating_ip:{floating_network_vim_id}": True,
            f"volume:{volume_id2}": True,
            f"volume:{volume_id}": True,
            f"port:{port_id}": None,
        }
        volumes_to_hold = []
        k = f"volume:{volume_id}"
        k_id = volume_id
        self.vimconn.cinder.volumes.get.return_value.status = "available"
        self.vimconn.cinder.volumes.delete.side_effect = cExceptions.ClientException(
            403, "Connection aborted."
        )
        result = self.vimconn._delete_volumes_by_id_wth_cinder(
            k, k_id, volumes_to_hold, created_items
        )
        self.assertEqual(result, None)
        self.vimconn.cinder.volumes.get.assert_called_once_with(k_id)
        self.vimconn.cinder.volumes.delete.assert_called_once_with(k_id)
        self.vimconn.logger.error.assert_called_once_with(
            "Error deleting volume: ClientException: Connection aborted. (HTTP 403)"
        )
        self.assertEqual(created_items, expected_created_items)

    def test_delete_volumes_by_id_with_cinder__delete_volume_raise_connection_exception__exception_is_raised(
        self,
    ):
        """cinder delete volume raises exception."""
        created_items = {
            f"floating_ip:{floating_network_vim_id}": True,
            f"volume:{volume_id2}": True,
            f"volume:{volume_id}": True,
            f"port:{port_id}": None,
        }
        expected_created_items = {
            f"floating_ip:{floating_network_vim_id}": True,
            f"volume:{volume_id2}": True,
            f"volume:{volume_id}": True,
            f"port:{port_id}": None,
        }
        volumes_to_hold = []
        k = f"volume:{volume_id}"
        k_id = volume_id
        self.vimconn.cinder.volumes.get.return_value.status = "available"
        self.vimconn.cinder.volumes.delete.side_effect = cExceptions.ConnectionError(
            "Connection failed."
        )
        with self.assertRaises(VimConnConnectionException):
            result = self.vimconn._delete_volumes_by_id_wth_cinder(
                k, k_id, volumes_to_hold, created_items
            )
            self.assertEqual(result, None)
        self.vimconn.cinder.volumes.get.assert_called_once_with(k_id)
        self.vimconn.cinder.volumes.delete.assert_called_once_with(k_id)
        self.vimconn.logger.error.assert_called_once_with(
            "Error deleting volume: ConnectionError: Connection failed."
        )
        self.assertEqual(created_items, expected_created_items)

    def test_delete_volumes_by_id_with_cinder_volume_to_be_hold(self):
        """volume_to_hold has item."""
        created_items = {
            f"floating_ip:{floating_network_vim_id}": True,
            f"volume:{volume_id2}": True,
            f"volume:{volume_id}": True,
            f"port:{port_id}": None,
        }
        expected_created_items = {
            f"floating_ip:{floating_network_vim_id}": True,
            f"volume:{volume_id2}": True,
            f"volume:{volume_id}": True,
            f"port:{port_id}": None,
        }
        volumes_to_hold = [volume_id]
        k = f"volume:{volume_id}"
        k_id = volume_id
        result = self.vimconn._delete_volumes_by_id_wth_cinder(
            k, k_id, volumes_to_hold, created_items
        )
        self.assertEqual(result, False)
        self.vimconn.cinder.volumes.get.assert_not_called()
        self.vimconn.cinder.volumes.delete.assert_not_called()
        self.vimconn.logger.error.assert_not_called()
        self.assertEqual(created_items, expected_created_items)

    def test_delete_volumes_by_id_with_cinder_volume_status_not_available(self):
        """volume status is not available."""
        created_items = {
            f"floating_ip:{floating_network_vim_id}": True,
            f"volume:{volume_id2}": True,
            f"volume:{volume_id}": True,
            f"port:{port_id}": None,
        }
        expected_created_items = {
            f"floating_ip:{floating_network_vim_id}": True,
            f"volume:{volume_id2}": True,
            f"volume:{volume_id}": True,
            f"port:{port_id}": None,
        }
        volumes_to_hold = []
        k = f"volume:{volume_id}"
        k_id = volume_id
        self.vimconn.cinder.volumes.get.return_value.status = "unavailable"
        result = self.vimconn._delete_volumes_by_id_wth_cinder(
            k, k_id, volumes_to_hold, created_items
        )
        self.assertEqual(result, True)
        self.vimconn.cinder.volumes.get.assert_called_once_with(k_id)
        self.vimconn.cinder.volumes.delete.assert_not_called()
        self.vimconn.logger.error.assert_not_called()
        self.assertEqual(created_items, expected_created_items)

    def test_delete_ports_by_id_by_neutron(self):
        """neutron delete ports."""
        k_id = port_id
        self.vimconn._delete_ports_by_id_wth_neutron(k_id)
        self.vimconn.neutron.delete_port.assert_called_once_with(k_id)
        self.vimconn.logger.error.assert_not_called()

    def test_delete_ports_by_id_by_neutron_delete_port_raise_exception(self):
        """neutron delete port raises exception."""
        k_id = port_id
        self.vimconn.neutron.delete_port.side_effect = nvExceptions.ClientException(
            "Connection aborted."
        )
        self.vimconn._delete_ports_by_id_wth_neutron(k_id)
        self.vimconn.neutron.delete_port.assert_called_once_with(k_id)
        self.vimconn.logger.error.assert_called_once_with(
            "Error deleting port: ClientException: Unknown Error (HTTP Connection aborted.)"
        )

    def test_get_item_name_id(self):
        """Get name and id successfully."""
        k = f"some:{port_id}"
        result = self.vimconn._get_item_name_id(k)
        self.assertEqual(result, ("some", f"{port_id}"))

    def test_get_item_name_id_wthout_semicolon(self):
        """Does not have seperator."""
        k = f"some{port_id}"
        result = self.vimconn._get_item_name_id(k)
        self.assertEqual(result, (f"some{port_id}", ""))

    def test_get_item_name_id_empty_string(self):
        """Empty string."""
        k = ""
        result = self.vimconn._get_item_name_id(k)
        self.assertEqual(result, ("", ""))

    def test_get_item_name_id_k_is_none(self):
        """item is None."""
        k = None
        with self.assertRaises(AttributeError):
            self.vimconn._get_item_name_id(k)

    @patch.object(vimconnector, "_get_item_name_id")
    @patch.object(vimconnector, "_delete_volumes_by_id_wth_cinder")
    @patch.object(vimconnector, "_delete_floating_ip_by_id")
    def test_delete_created_items(
        self,
        mock_delete_floating_ip_by_id,
        mock_delete_volumes_by_id_wth_cinder,
        mock_get_item_name_id,
    ):
        """Created items has floating ip and volume."""
        created_items = {
            f"floating_ip:{floating_network_vim_id}": True,
            f"volume:{volume_id}": True,
            f"port:{port_id}": None,
        }
        mock_get_item_name_id.side_effect = [
            ("floating_ip", f"{floating_network_vim_id}"),
            ("volume", f"{volume_id}"),
        ]
        mock_delete_volumes_by_id_wth_cinder.return_value = True
        volumes_to_hold = []
        keep_waiting = False
        result = self.vimconn._delete_created_items(
            created_items, volumes_to_hold, keep_waiting
        )
        self.assertEqual(result, True)
        self.assertEqual(mock_get_item_name_id.call_count, 2)
        mock_delete_volumes_by_id_wth_cinder.assert_called_once_with(
            f"volume:{volume_id}", f"{volume_id}", [], created_items
        )
        mock_delete_floating_ip_by_id.assert_called_once_with(
            f"floating_ip:{floating_network_vim_id}",
            f"{floating_network_vim_id}",
            created_items,
        )
        self.vimconn.logger.error.assert_not_called()

    @patch.object(vimconnector, "_get_item_name_id")
    @patch.object(vimconnector, "_delete_volumes_by_id_wth_cinder")
    @patch.object(vimconnector, "_delete_floating_ip_by_id")
    def test_delete_created_items_wth_volumes_to_hold(
        self,
        mock_delete_floating_ip_by_id,
        mock_delete_volumes_by_id_wth_cinder,
        mock_get_item_name_id,
    ):
        """Created items has floating ip and volume and volumes_to_hold has items."""
        created_items = {
            f"floating_ip:{floating_network_vim_id}": True,
            f"volume:{volume_id}": True,
            f"port:{port_id}": None,
        }
        mock_get_item_name_id.side_effect = [
            ("floating_ip", f"{floating_network_vim_id}"),
            ("volume", f"{volume_id}"),
        ]
        mock_delete_volumes_by_id_wth_cinder.return_value = True
        volumes_to_hold = [f"{volume_id}", f"{volume_id2}"]
        keep_waiting = False
        result = self.vimconn._delete_created_items(
            created_items, volumes_to_hold, keep_waiting
        )
        self.assertEqual(result, True)
        self.assertEqual(mock_get_item_name_id.call_count, 2)
        mock_delete_volumes_by_id_wth_cinder.assert_called_once_with(
            f"volume:{volume_id}", f"{volume_id}", volumes_to_hold, created_items
        )
        mock_delete_floating_ip_by_id.assert_called_once_with(
            f"floating_ip:{floating_network_vim_id}",
            f"{floating_network_vim_id}",
            created_items,
        )
        self.vimconn.logger.error.assert_not_called()

    @patch.object(vimconnector, "_get_item_name_id")
    @patch.object(vimconnector, "_delete_volumes_by_id_wth_cinder")
    @patch.object(vimconnector, "_delete_floating_ip_by_id")
    def test_delete_created_items_wth_keep_waiting_true(
        self,
        mock_delete_floating_ip_by_id,
        mock_delete_volumes_by_id_wth_cinder,
        mock_get_item_name_id,
    ):
        """Keep waiting initial value is True."""
        created_items = {
            f"floating_ip:{floating_network_vim_id}": True,
            f"volume:{volume_id}": True,
            f"port:{port_id}": None,
        }
        mock_get_item_name_id.side_effect = [
            ("floating_ip", f"{floating_network_vim_id}"),
            ("volume", f"{volume_id}"),
        ]
        mock_delete_volumes_by_id_wth_cinder.return_value = False
        volumes_to_hold = [f"{volume_id}", f"{volume_id2}"]
        keep_waiting = True
        result = self.vimconn._delete_created_items(
            created_items, volumes_to_hold, keep_waiting
        )
        self.assertEqual(result, True)
        self.assertEqual(mock_get_item_name_id.call_count, 2)
        mock_delete_volumes_by_id_wth_cinder.assert_called_once_with(
            f"volume:{volume_id}", f"{volume_id}", volumes_to_hold, created_items
        )
        mock_delete_floating_ip_by_id.assert_called_once_with(
            f"floating_ip:{floating_network_vim_id}",
            f"{floating_network_vim_id}",
            created_items,
        )
        self.vimconn.logger.error.assert_not_called()

    @patch.object(vimconnector, "_get_item_name_id")
    @patch.object(vimconnector, "_delete_volumes_by_id_wth_cinder")
    @patch.object(vimconnector, "_delete_floating_ip_by_id")
    def test_delete_created_items__delete_vol_raises_connection_error__operation_fails(
        self,
        mock_delete_floating_ip_by_id,
        mock_delete_volumes_by_id_wth_cinder,
        mock_get_item_name_id,
    ):
        """Delete volume raises exception."""
        created_items = {
            f"floating_ip:{floating_network_vim_id}": True,
            f"volume:{volume_id}": True,
            f"port:{port_id}": None,
        }
        mock_get_item_name_id.side_effect = [
            ("floating_ip", f"{floating_network_vim_id}"),
            ("volume", f"{volume_id}"),
        ]
        mock_delete_volumes_by_id_wth_cinder.side_effect = (
            neExceptions.ConnectionFailed("Connection failed.")
        )
        volumes_to_hold = []
        keep_waiting = False
        with self.assertRaises(VimConnConnectionException):
            result = self.vimconn._delete_created_items(
                created_items, volumes_to_hold, keep_waiting
            )
            self.assertEqual(result, None)
        self.assertEqual(mock_get_item_name_id.call_count, 2)
        mock_delete_volumes_by_id_wth_cinder.assert_called_once_with(
            f"volume:{volume_id}", f"{volume_id}", [], created_items
        )
        mock_delete_floating_ip_by_id.assert_called_once_with(
            f"floating_ip:{floating_network_vim_id}",
            f"{floating_network_vim_id}",
            created_items,
        )
        self.vimconn.logger.error.assert_called_once_with(
            "Error deleting volume:ac408b73-b9cc-4a6a-a270-82cc4811bd4a: Connection failed."
        )

    @patch.object(vimconnector, "_get_item_name_id")
    @patch.object(vimconnector, "_delete_volumes_by_id_wth_cinder")
    @patch.object(vimconnector, "_delete_floating_ip_by_id")
    def test_delete_created_items__delete_fip_raises_connection_error__operation_fails(
        self,
        mock_delete_floating_ip_by_id,
        mock_delete_volumes_by_id_wth_cinder,
        mock_get_item_name_id,
    ):
        """Delete floating ip raises exception."""
        created_items = {
            f"floating_ip:{floating_network_vim_id}": True,
            f"volume:{volume_id}": True,
            f"port:{port_id}": None,
        }
        mock_get_item_name_id.side_effect = [
            ("floating_ip", f"{floating_network_vim_id}"),
            ("volume", f"{volume_id}"),
        ]
        mock_delete_volumes_by_id_wth_cinder.return_value = False
        mock_delete_floating_ip_by_id.side_effect = ConnectionError(
            "Connection failed."
        )
        volumes_to_hold = []
        keep_waiting = True
        with self.assertRaises(VimConnConnectionException):
            result = self.vimconn._delete_created_items(
                created_items, volumes_to_hold, keep_waiting
            )
            self.assertEqual(result, None)
        self.assertEqual(mock_get_item_name_id.call_count, 1)
        mock_delete_volumes_by_id_wth_cinder.assert_not_called()
        mock_delete_floating_ip_by_id.assert_called_once_with(
            f"floating_ip:{floating_network_vim_id}",
            f"{floating_network_vim_id}",
            created_items,
        )
        self.vimconn.logger.error.assert_called_once_with(
            "Error deleting floating_ip:108b73-e9cc-5a6a-t270-82cc4811bd4a: Connection failed."
        )

    @patch.object(vimconnector, "_get_item_name_id")
    @patch.object(vimconnector, "_delete_volumes_by_id_wth_cinder")
    @patch.object(vimconnector, "_delete_floating_ip_by_id")
    def test_delete_created_items_get_item_name_raises_type_error__operation_fails(
        self,
        mock_delete_floating_ip_by_id,
        mock_delete_volumes_by_id_wth_cinder,
        mock_get_item_name_id,
    ):
        """Get item, name raises exception."""
        created_items = {
            3: True,
            f"volume{volume_id}": True,
            f"port:{port_id}": None,
        }
        mock_get_item_name_id.side_effect = [
            TypeError("Invalid Type"),
            AttributeError("Invalid attribute"),
        ]
        volumes_to_hold = []
        keep_waiting = False
        with self.assertRaises(VimConnException):
            result = self.vimconn._delete_created_items(
                created_items, volumes_to_hold, keep_waiting
            )
            self.assertEqual(result, None)
        self.assertEqual(mock_get_item_name_id.call_count, 1)
        mock_delete_volumes_by_id_wth_cinder.assert_not_called()
        mock_delete_floating_ip_by_id.assert_not_called()
        _call_logger = self.vimconn.logger.error.call_args_list
        self.assertEqual(_call_logger[0][0], ("Error deleting 3: Invalid Type",))

    @patch.object(vimconnector, "_get_item_name_id")
    @patch.object(vimconnector, "_delete_volumes_by_id_wth_cinder")
    @patch.object(vimconnector, "_delete_floating_ip_by_id")
    def test_delete_created_items_no_fip_wth_port(
        self,
        mock_delete_floating_ip_by_id,
        mock_delete_volumes_by_id_wth_cinder,
        mock_get_item_name_id,
    ):
        """Created items has port, does not have floating ip."""
        created_items = {
            f"volume:{volume_id}": True,
            f"port:{port_id}": True,
        }
        mock_get_item_name_id.side_effect = [
            ("volume", f"{volume_id}"),
            ("port", f"{port_id}"),
        ]
        mock_delete_volumes_by_id_wth_cinder.return_value = False
        volumes_to_hold = []
        keep_waiting = False
        result = self.vimconn._delete_created_items(
            created_items, volumes_to_hold, keep_waiting
        )
        self.assertEqual(result, False)
        self.assertEqual(mock_get_item_name_id.call_count, 2)
        mock_delete_volumes_by_id_wth_cinder.assert_called_once_with(
            f"volume:{volume_id}", f"{volume_id}", [], created_items
        )
        mock_delete_floating_ip_by_id.assert_not_called()
        self.vimconn.logger.error.assert_not_called()

    @patch.object(vimconnector, "_get_item_name_id")
    @patch.object(vimconnector, "_delete_volumes_by_id_wth_cinder")
    @patch.object(vimconnector, "_delete_floating_ip_by_id")
    def test_delete_created_items_no_volume(
        self,
        mock_delete_floating_ip_by_id,
        mock_delete_volumes_by_id_wth_cinder,
        mock_get_item_name_id,
    ):
        """Created items does not have volume."""
        created_items = {
            f"floating_ip:{floating_network_vim_id}": True,
            f"port:{port_id}": None,
        }
        mock_get_item_name_id.side_effect = [
            ("floating_ip", f"{floating_network_vim_id}")
        ]
        volumes_to_hold = []
        keep_waiting = False
        result = self.vimconn._delete_created_items(
            created_items, volumes_to_hold, keep_waiting
        )
        self.assertEqual(result, False)
        self.assertEqual(mock_get_item_name_id.call_count, 1)
        mock_delete_volumes_by_id_wth_cinder.assert_not_called()
        mock_delete_floating_ip_by_id.assert_called_once_with(
            f"floating_ip:{floating_network_vim_id}",
            f"{floating_network_vim_id}",
            created_items,
        )
        self.vimconn.logger.error.assert_not_called()

    @patch.object(vimconnector, "_get_item_name_id")
    @patch.object(vimconnector, "_delete_volumes_by_id_wth_cinder")
    @patch.object(vimconnector, "_delete_floating_ip_by_id")
    def test_delete_created_items_already_deleted(
        self,
        mock_delete_floating_ip_by_id,
        mock_delete_volumes_by_id_wth_cinder,
        mock_get_item_name_id,
    ):
        """All created items are alerady deleted."""
        created_items = {
            f"floating_ip:{floating_network_vim_id}": None,
            f"volume:{volume_id}": None,
            f"port:{port_id}": None,
        }
        volumes_to_hold = []
        keep_waiting = False
        result = self.vimconn._delete_created_items(
            created_items, volumes_to_hold, keep_waiting
        )
        self.assertEqual(result, False)
        mock_get_item_name_id.assert_not_called()
        mock_delete_volumes_by_id_wth_cinder.assert_not_called()
        mock_delete_floating_ip_by_id.assert_not_called()
        self.vimconn.logger.error.assert_not_called()

    @patch("time.sleep")
    @patch.object(vimconnector, "_extract_items_wth_keep_flag_from_created_items")
    @patch.object(vimconnector, "_format_exception")
    @patch.object(vimconnector, "_reload_connection")
    @patch.object(vimconnector, "_delete_vm_ports_attached_to_network")
    @patch.object(vimconnector, "_delete_created_items")
    def test_delete_vminstance_successfully(
        self,
        mock_delete_created_items,
        mock_delete_vm_ports_attached_to_network,
        mock_reload_connection,
        mock_format_exception,
        mock_extract_items_wth_keep_flag_from_created_items,
        mock_sleep,
    ):
        vm_id = f"{virtual_mac_id}"
        created_items = deepcopy(created_items_all_true)
        mock_extract_items_wth_keep_flag_from_created_items.return_value = created_items
        volumes_to_hold = [f"{volume_id}", f"{volume_id2}"]
        mock_delete_created_items.return_value = False
        self.vimconn.delete_vminstance(vm_id, created_items, volumes_to_hold)
        mock_reload_connection.assert_called_once()
        mock_delete_vm_ports_attached_to_network.assert_called_once_with(created_items)
        self.vimconn.nova.servers.delete.assert_called_once_with(vm_id)
        mock_delete_created_items.assert_called_once_with(
            created_items, volumes_to_hold, False
        )
        mock_sleep.assert_not_called()
        mock_format_exception.assert_not_called()
        mock_extract_items_wth_keep_flag_from_created_items.assert_called_once_with(
            created_items
        )

    @patch("time.sleep")
    @patch.object(vimconnector, "_extract_items_wth_keep_flag_from_created_items")
    @patch.object(vimconnector, "_format_exception")
    @patch.object(vimconnector, "_reload_connection")
    @patch.object(vimconnector, "_delete_vm_ports_attached_to_network")
    @patch.object(vimconnector, "_delete_created_items")
    def test_delete_vminstance_created_items_has_keep_flag(
        self,
        mock_delete_created_items,
        mock_delete_vm_ports_attached_to_network,
        mock_reload_connection,
        mock_format_exception,
        mock_extract_items_wth_keep_flag_from_created_items,
        mock_sleep,
    ):
        """Created_items includes items which has keep flag."""
        vm_id = f"{virtual_mac_id}"
        initial_created_items = {
            f"port{port_id}": True,
            f"floating_ip{floating_network_vim_id}": None,
            f"volume{volume_id}keep": True,
            f"volume{volume_id2}keep": True,
        }
        created_items = {
            f"port{port_id}": True,
            f"floating_ip{floating_network_vim_id}": None,
        }
        mock_extract_items_wth_keep_flag_from_created_items.return_value = created_items
        volumes_to_hold = []
        mock_delete_created_items.return_value = False
        self.vimconn.delete_vminstance(vm_id, initial_created_items, volumes_to_hold)
        mock_reload_connection.assert_called_once()
        mock_delete_vm_ports_attached_to_network.assert_called_once_with(created_items)
        self.vimconn.nova.servers.delete.assert_called_once_with(vm_id)
        mock_delete_created_items.assert_called_once_with(
            created_items, volumes_to_hold, False
        )
        mock_sleep.assert_not_called()
        mock_format_exception.assert_not_called()
        mock_extract_items_wth_keep_flag_from_created_items.assert_called_once_with(
            initial_created_items
        )

    @patch("time.sleep")
    @patch.object(vimconnector, "_extract_items_wth_keep_flag_from_created_items")
    @patch.object(vimconnector, "_reload_connection")
    @patch.object(vimconnector, "_delete_vm_ports_attached_to_network")
    @patch.object(vimconnector, "_delete_created_items")
    def test_delete_vminstance__extract_items_wth_keep_raises_attributeerror__raise_vimconnexception(
        self,
        mock_delete_created_items,
        mock_delete_vm_ports_attached_to_network,
        mock_reload_connection,
        mock_extract_items_wth_keep_flag_from_created_items,
        mock_sleep,
    ):
        """extract_items_wth_keep_flag_from_created_items raises AttributeError."""
        vm_id = f"{virtual_mac_id}"
        initial_created_items = {
            f"port{port_id}": True,
            f"floating_ip{floating_network_vim_id}": None,
            f"volume{volume_id}keep": True,
            f"volume{volume_id2}keep": True,
        }

        mock_extract_items_wth_keep_flag_from_created_items.side_effect = AttributeError
        volumes_to_hold = []
        mock_delete_created_items.return_value = False
        with self.assertRaises(VimConnException):
            self.vimconn.delete_vminstance(
                vm_id, initial_created_items, volumes_to_hold
            )
        mock_reload_connection.assert_not_called()
        mock_delete_vm_ports_attached_to_network.assert_not_called()
        self.vimconn.nova.servers.delete.assert_not_called()
        mock_delete_created_items.assert_not_called()
        mock_sleep.assert_not_called()
        mock_extract_items_wth_keep_flag_from_created_items.assert_called_once_with(
            initial_created_items
        )

    @patch("time.sleep")
    @patch.object(vimconnector, "_extract_items_wth_keep_flag_from_created_items")
    @patch.object(vimconnector, "_format_exception")
    @patch.object(vimconnector, "_reload_connection")
    @patch.object(vimconnector, "_delete_vm_ports_attached_to_network")
    @patch.object(vimconnector, "_delete_created_items")
    def test_delete_vminstance__delete_created_items_returns_true__delete_created_items_called_several_times(
        self,
        mock_delete_created_items,
        mock_delete_vm_ports_attached_to_network,
        mock_reload_connection,
        mock_format_exception,
        mock_extract_items_wth_keep_flag_from_created_items,
        mock_sleep,
    ):
        """Delete creted items raises exception."""
        vm_id = f"{virtual_mac_id}"
        created_items = deepcopy(created_items_all_true)
        mock_extract_items_wth_keep_flag_from_created_items.return_value = created_items
        mock_sleep = MagicMock()
        volumes_to_hold = []
        mock_delete_created_items.side_effect = [True, False]
        self.vimconn.delete_vminstance(vm_id, created_items, volumes_to_hold)
        mock_reload_connection.assert_called_once()
        mock_delete_vm_ports_attached_to_network.assert_called_once_with(created_items)
        self.vimconn.nova.servers.delete.assert_called_once_with(vm_id)
        self.assertEqual(mock_delete_created_items.call_count, 2)
        mock_sleep.assert_not_called()
        mock_extract_items_wth_keep_flag_from_created_items.assert_called_once_with(
            created_items
        )

    @patch("time.sleep")
    @patch.object(vimconnector, "_extract_items_wth_keep_flag_from_created_items")
    @patch.object(vimconnector, "_reload_connection")
    @patch.object(vimconnector, "_delete_vm_ports_attached_to_network")
    @patch.object(vimconnector, "_delete_created_items")
    def test_delete_vminstance__delete_vm_ports_raises_connection_error__raise_vimconnconnectionexception(
        self,
        mock_delete_created_items,
        mock_delete_vm_ports_attached_to_network,
        mock_reload_connection,
        mock_extract_items_wth_keep_flag_from_created_items,
        mock_sleep,
    ):
        """Delete vm ports raises exception."""
        vm_id = f"{virtual_mac_id}"
        created_items = deepcopy(created_items_all_true)
        mock_extract_items_wth_keep_flag_from_created_items.return_value = created_items
        volumes_to_hold = [f"{volume_id}", f"{volume_id2}"]
        err = ConnectionError("ClientException occurred.")
        mock_delete_vm_ports_attached_to_network.side_effect = err
        mock_delete_created_items.return_value = False
        with self.assertRaises(VimConnConnectionException):
            self.vimconn.delete_vminstance(vm_id, created_items, volumes_to_hold)
        mock_reload_connection.assert_called_once()
        mock_delete_vm_ports_attached_to_network.assert_called_once_with(created_items)
        self.vimconn.nova.servers.delete.assert_not_called()
        mock_delete_created_items.assert_not_called()
        mock_sleep.assert_not_called()
        mock_extract_items_wth_keep_flag_from_created_items.assert_called_once_with(
            created_items
        )

    @patch("time.sleep")
    @patch.object(vimconnector, "_extract_items_wth_keep_flag_from_created_items")
    @patch.object(vimconnector, "_reload_connection")
    @patch.object(vimconnector, "_delete_vm_ports_attached_to_network")
    @patch.object(vimconnector, "_delete_created_items")
    def test_delete_vminstance__nova_server_delete_raises_clientexception__raise_vimconn_unexpected_response(
        self,
        mock_delete_created_items,
        mock_delete_vm_ports_attached_to_network,
        mock_reload_connection,
        mock_extract_items_wth_keep_flag_from_created_items,
        mock_sleep,
    ):
        """Nova server delete raises exception."""
        vm_id = f"{virtual_mac_id}"
        created_items = deepcopy(created_items_all_true)
        mock_extract_items_wth_keep_flag_from_created_items.return_value = created_items
        volumes_to_hold = [f"{volume_id}", f"{volume_id2}"]
        err = nvExceptions.ClientException("ClientException occurred.")
        self.vimconn.nova.servers.delete.side_effect = err
        mock_delete_created_items.side_effect = err
        with self.assertRaises(VimConnUnexpectedResponse):
            self.vimconn.delete_vminstance(vm_id, created_items, volumes_to_hold)
        mock_reload_connection.assert_called_once()
        mock_delete_vm_ports_attached_to_network.assert_called_once_with(created_items)
        self.vimconn.nova.servers.delete.assert_called_once_with(vm_id)
        mock_delete_created_items.assert_not_called()
        mock_sleep.assert_not_called()
        mock_extract_items_wth_keep_flag_from_created_items.assert_called_once_with(
            created_items
        )

    @patch("time.sleep")
    @patch.object(vimconnector, "_extract_items_wth_keep_flag_from_created_items")
    @patch.object(vimconnector, "_reload_connection")
    @patch.object(vimconnector, "_delete_vm_ports_attached_to_network")
    @patch.object(vimconnector, "_delete_created_items")
    def test_delete_vminstance__reload_connection_raises_connection_error__raises_vimconnconnection_exception(
        self,
        mock_delete_created_items,
        mock_delete_vm_ports_attached_to_network,
        mock_reload_connection,
        mock_extract_items_wth_keep_flag_from_created_items,
        mock_sleep,
    ):
        """Reload connection raises exception."""
        vm_id = f"{virtual_mac_id}"
        created_items = deepcopy(created_items_all_true)
        mock_extract_items_wth_keep_flag_from_created_items.return_value = created_items
        mock_sleep = MagicMock()
        volumes_to_hold = [f"{volume_id}", f"{volume_id2}"]
        err = ConnectionError("ClientException occurred.")
        mock_delete_created_items.return_value = False
        mock_reload_connection.side_effect = err
        with self.assertRaises(VimConnConnectionException):
            self.vimconn.delete_vminstance(vm_id, created_items, volumes_to_hold)
        mock_reload_connection.assert_called_once()
        mock_delete_vm_ports_attached_to_network.assert_not_called()
        self.vimconn.nova.servers.delete.assert_not_called()
        mock_delete_created_items.assert_not_called()
        mock_sleep.assert_not_called()
        mock_extract_items_wth_keep_flag_from_created_items.assert_called_once_with(
            created_items
        )

    @patch("time.sleep")
    @patch.object(vimconnector, "_extract_items_wth_keep_flag_from_created_items")
    @patch.object(vimconnector, "_format_exception")
    @patch.object(vimconnector, "_reload_connection")
    @patch.object(vimconnector, "_delete_vm_ports_attached_to_network")
    @patch.object(vimconnector, "_delete_created_items")
    def test_delete_vminstance_created_item_vol_to_hold_are_none(
        self,
        mock_delete_created_items,
        mock_delete_vm_ports_attached_to_network,
        mock_reload_connection,
        mock_format_exception,
        mock_extract_items_wth_keep_flag_from_created_items,
        mock_sleep,
    ):
        """created_items and volumes_to_hold are None."""
        vm_id = f"{virtual_mac_id}"
        created_items = None
        volumes_to_hold = None
        mock_extract_items_wth_keep_flag_from_created_items.return_value = {}
        mock_delete_created_items.return_value = False
        self.vimconn.delete_vminstance(vm_id, created_items, volumes_to_hold)
        mock_reload_connection.assert_called_once()
        mock_delete_vm_ports_attached_to_network.assert_not_called()
        self.vimconn.nova.servers.delete.assert_called_once_with(vm_id)
        mock_delete_created_items.assert_called_once_with({}, [], False)
        mock_sleep.assert_not_called()
        mock_format_exception.assert_not_called()
        mock_extract_items_wth_keep_flag_from_created_items.assert_called_once_with({})

    @patch("time.sleep")
    @patch.object(vimconnector, "_extract_items_wth_keep_flag_from_created_items")
    @patch.object(vimconnector, "_format_exception")
    @patch.object(vimconnector, "_reload_connection")
    @patch.object(vimconnector, "_delete_vm_ports_attached_to_network")
    @patch.object(vimconnector, "_delete_created_items")
    def test_delete_vminstance_vm_id_is_none(
        self,
        mock_delete_created_items,
        mock_delete_vm_ports_attached_to_network,
        mock_reload_connection,
        mock_format_exception,
        mock_extract_items_wth_keep_flag_from_created_items,
        mock_sleep,
    ):
        """vm_id is None."""
        vm_id = None
        created_items = deepcopy(created_items_all_true)
        mock_extract_items_wth_keep_flag_from_created_items.return_value = created_items
        volumes_to_hold = [f"{volume_id}", f"{volume_id2}"]
        mock_delete_created_items.side_effect = [True, True, False]
        self.vimconn.delete_vminstance(vm_id, created_items, volumes_to_hold)
        mock_reload_connection.assert_called_once()
        mock_delete_vm_ports_attached_to_network.assert_called_once_with(created_items)
        self.vimconn.nova.servers.delete.assert_not_called()
        self.assertEqual(mock_delete_created_items.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)
        mock_format_exception.assert_not_called()
        mock_extract_items_wth_keep_flag_from_created_items.assert_called_once_with(
            created_items
        )

    @patch("time.sleep")
    @patch.object(vimconnector, "_extract_items_wth_keep_flag_from_created_items")
    @patch.object(vimconnector, "_format_exception")
    @patch.object(vimconnector, "_reload_connection")
    @patch.object(vimconnector, "_delete_vm_ports_attached_to_network")
    @patch.object(vimconnector, "_delete_created_items")
    def test_delete_vminstance_delete_created_items_return_true(
        self,
        mock_delete_created_items,
        mock_delete_vm_ports_attached_to_network,
        mock_reload_connection,
        mock_format_exception,
        mock_extract_items_wth_keep_flag_from_created_items,
        mock_sleep,
    ):
        """Delete created items always return True."""
        vm_id = None
        created_items = deepcopy(created_items_all_true)
        mock_extract_items_wth_keep_flag_from_created_items.return_value = created_items
        volumes_to_hold = [f"{volume_id}", f"{volume_id2}"]
        mock_delete_created_items.side_effect = [True] * 1800
        self.vimconn.delete_vminstance(vm_id, created_items, volumes_to_hold)
        mock_reload_connection.assert_called_once()
        mock_delete_vm_ports_attached_to_network.assert_called_once_with(created_items)
        self.vimconn.nova.servers.delete.assert_not_called()
        self.assertEqual(mock_delete_created_items.call_count, 1800)
        self.assertEqual(mock_sleep.call_count, 1800)
        mock_format_exception.assert_not_called()
        mock_extract_items_wth_keep_flag_from_created_items.assert_called_once_with(
            created_items
        )

    def test_remove_keep_tag_from_persistent_volumes_keep_flag_exists(self):
        """Keep flag exists in created items."""
        created_items = {
            f"port:{port_id}": True,
            f"floating_ip:{floating_network_vim_id}": True,
            f"volume:{volume_id}:keep": True,
            f"volume:{volume_id2}:keep": True,
        }
        expected_result = {
            f"port:{port_id}": True,
            f"floating_ip:{floating_network_vim_id}": True,
            f"volume:{volume_id}": True,
            f"volume:{volume_id2}": True,
        }
        result = self.vimconn.remove_keep_tag_from_persistent_volumes(created_items)
        self.assertDictEqual(result, expected_result)

    def test_remove_keep_tag_from_persistent_volumes_without_keep_flag(self):
        """Keep flag does not exist in created items."""
        created_items = {
            f"port:{port_id}": True,
            f"floating_ip:{floating_network_vim_id}": True,
            f"volume:{volume_id}": True,
            f"volume:{volume_id2}": True,
        }
        result = self.vimconn.remove_keep_tag_from_persistent_volumes(created_items)
        self.assertDictEqual(result, created_items)

    def test_update_block_device_mapping_empty_volume(self):
        volume = ""
        block_device_mapping = {}
        base_disk_index = 100
        disk = {}
        created_items = {}
        with self.assertRaises(VimConnException) as err:
            self.vimconn.update_block_device_mapping(
                volume, block_device_mapping, base_disk_index, disk, created_items
            )
            self.assertEqual(str(err), "Volume is empty.")
        self.assertEqual(block_device_mapping, {})
        self.assertEqual(created_items, {})

    def test_update_block_device_mapping_invalid_volume(self):
        volume = "Volume-A"
        block_device_mapping = {}
        base_disk_index = 100
        disk = {}
        created_items = {}
        with self.assertRaises(VimConnException) as err:
            self.vimconn.update_block_device_mapping(
                volume, block_device_mapping, base_disk_index, disk, created_items
            )
            self.assertEqual(
                str(err), "Created volume is not valid, does not have id attribute."
            )
        self.assertEqual(block_device_mapping, {})
        self.assertEqual(created_items, {})

    def test_update_block_device_mapping(self):
        volume = MagicMock(autospec=True)
        volume.id = volume_id
        block_device_mapping = {}
        base_disk_index = 100
        disk = {}
        created_items = {}
        self.vimconn.update_block_device_mapping(
            volume, block_device_mapping, base_disk_index, disk, created_items
        )
        self.assertEqual(
            block_device_mapping, {"vdd": "ac408b73-b9cc-4a6a-a270-82cc4811bd4a"}
        )
        self.assertEqual(
            created_items, {"volume:ac408b73-b9cc-4a6a-a270-82cc4811bd4a": True}
        )

    def test_update_block_device_mapping_with_keep_flag(self):
        volume = MagicMock(autospec=True)
        volume.id = volume_id
        block_device_mapping = {}
        base_disk_index = 100
        disk = {"size": 10, "keep": True}
        created_items = {}
        self.vimconn.update_block_device_mapping(
            volume, block_device_mapping, base_disk_index, disk, created_items
        )
        self.assertEqual(
            block_device_mapping, {"vdd": "ac408b73-b9cc-4a6a-a270-82cc4811bd4a"}
        )
        self.assertEqual(
            created_items, {"volume:ac408b73-b9cc-4a6a-a270-82cc4811bd4a:keep": True}
        )

    def test_extract_items_with_keep_flag_item_has_keep_flag(self):
        created_items = deepcopy(created_items_all_true)
        created_items[f"volume:{volume_id2}:keep"] = True
        result = self.vimconn._extract_items_wth_keep_flag_from_created_items(
            created_items
        )
        self.assertEqual(result, deepcopy(created_items_all_true))

    def test_extract_items_with_keep_flag_no_item_wth_keep_flag(self):
        created_items = deepcopy(created_items_all_true)
        result = self.vimconn._extract_items_wth_keep_flag_from_created_items(
            created_items
        )
        self.assertEqual(result, deepcopy(created_items_all_true))

    def test_extract_items_with_keep_flag_all_items_are_already_deleted(self):
        created_items = {
            f"port:{port_id}": None,
            f"floating_ip:{floating_network_vim_id}": None,
            f"volume:{volume_id}:keep": None,
            f"volume:{volume_id2}:keep": None,
        }
        expected_result = {
            f"port:{port_id}": None,
            f"floating_ip:{floating_network_vim_id}": None,
        }
        result = self.vimconn._extract_items_wth_keep_flag_from_created_items(
            created_items
        )
        self.assertEqual(result, expected_result)

    def test_extract_items_with_keep_flag_without_semicolon(self):
        created_items = {
            f"port{port_id}": True,
            f"floating_ip{floating_network_vim_id}": None,
            f"volume{volume_id}keep": True,
            f"volume{volume_id2}keep": True,
        }
        result = self.vimconn._extract_items_wth_keep_flag_from_created_items(
            created_items
        )
        self.assertEqual(result, {})

    def test_extract_items_with_keep_flag_invalid_type_created_items(self):
        created_items = [{f"port{port_id}": True}, {f"volume{volume_id2}keep": True}]
        with self.assertRaises(AttributeError):
            self.vimconn._extract_items_wth_keep_flag_from_created_items(created_items)

    @patch.object(vimconnector, "_reload_connection", new_callable=CopyingMock())
    def test_get_monitoring_data(self, mock_reload_conection):
        flavors = [
            {"original_name": "flavor1", "id": "367fc1eb-bd22-40f8-a519-ed2fb4e5976b"},
            {"original_name": "flavor2", "id": "5dcf9732-d17d-40b3-910d-37fc4c5aacc0"},
        ]
        servers = [
            Server(
                "server1", "ACTIVE", flavors[0], "312200db-42e3-4772-9518-d5db85468392"
            ),
            Server(
                "server2", "ACTIVE", flavors[1], "39a166cf-e4e6-479c-b88c-9ad558cf2cbf"
            ),
        ]
        ports = {"ports": ["port1", "port2"]}
        self.vimconn.nova.servers.list.return_value = servers
        self.vimconn.neutron.list_ports.return_value = ports
        result = self.vimconn.get_monitoring_data()
        self.assertTupleEqual(result, (servers, ports))
        mock_reload_conection.assert_called_once()
        self.vimconn.nova.servers.list.assert_called_once_with(detailed=True)
        self.vimconn.neutron.list_ports.assert_called_once()

    @patch.object(vimconnector, "_reload_connection", new_callable=CopyingMock())
    def test_get_monitoring_data_reload_connection_raises(self, mock_reload_conection):
        mock_reload_conection.side_effect = VimConnNotFoundException(
            "Connection object not found."
        )
        with self.assertRaises(VimConnException) as err:
            result = self.vimconn.get_monitoring_data()
            self.assertTupleEqual(result, None)
        self.assertEqual(
            str(err.exception.args[0]),
            "Exception in monitoring while getting VMs and ports status: Connection object not found.",
        )
        mock_reload_conection.assert_called_once()
        check_if_assert_not_called(
            [self.vimconn.nova.servers.list, self.vimconn.neutron.list_ports]
        )

    @patch.object(vimconnector, "_reload_connection", new_callable=CopyingMock())
    def test_get_monitoring_data_server_list_raises(self, mock_reload_conection):
        self.vimconn.nova.servers.list.side_effect = VimConnConnectionException(
            "Can not connect to Cloud API."
        )
        with self.assertRaises(VimConnException) as err:
            result = self.vimconn.get_monitoring_data()
            self.assertTupleEqual(result, None)
        self.assertEqual(
            str(err.exception.args[0]),
            "Exception in monitoring while getting VMs and ports status: Can not connect to Cloud API.",
        )
        mock_reload_conection.assert_called_once()
        self.vimconn.nova.servers.list.assert_called_once_with(detailed=True)
        self.vimconn.neutron.list_ports.assert_not_called()

    @patch.object(vimconnector, "_reload_connection", new_callable=CopyingMock())
    def test_get_monitoring_data_list_ports_raises(self, mock_reload_conection):
        self.vimconn.neutron.list_ports.side_effect = VimConnConnectionException(
            "Can not connect to Cloud API."
        )
        with self.assertRaises(VimConnException) as err:
            result = self.vimconn.get_monitoring_data()
            self.assertTupleEqual(result, None)
        self.assertEqual(
            str(err.exception.args[0]),
            "Exception in monitoring while getting VMs and ports status: Can not connect to Cloud API.",
        )
        mock_reload_conection.assert_called_once()
        self.vimconn.nova.servers.list.assert_called_once_with(detailed=True)
        self.vimconn.neutron.list_ports.assert_called_once()


class TestNewFlavor(unittest.TestCase):
    @patch("logging.getLogger", autospec=True)
    def setUp(self, mock_logger):
        # We are disabling the logging of exception not to print them to console.
        mock_logger = logging.getLogger()
        mock_logger.disabled = True
        self.vimconn = vimconnector(
            "123",
            "openstackvim",
            "456",
            "789",
            "http://dummy.url",
            None,
            "user",
            "pass",
        )
        self.vimconn.nova = CopyingMock(autospec=True)
        self.flavor1 = CopyingMock(autospec=True, name="sample-flavor")
        self.flavor2 = CopyingMock(autospec=True, name="other-flavor")
        self.new_flavor = CopyingMock(autospec=True, name="new_flavor")
        self.new_flavor.id = "075d2482-5edb-43e3-91b3-234e65b6268a"
        self.vimconn.nova.flavors.create.return_value = self.new_flavor

    @patch.object(vimconnector, "process_vio_numa_nodes", new_callable=CopyingMock())
    @patch.object(vimconnector, "process_numa_memory", new_callable=CopyingMock())
    @patch.object(vimconnector, "process_numa_vcpu", new_callable=CopyingMock())
    @patch.object(
        vimconnector,
        "process_numa_paired_threads",
        new_callable=CopyingMock(),
    )
    @patch.object(vimconnector, "process_numa_cores", new_callable=CopyingMock())
    @patch.object(vimconnector, "process_numa_threads", new_callable=CopyingMock())
    def test_process_numa_parameters_of_flavor_id_memory_vcpu_in_numa_type_vio(
        self,
        mock_process_numa_threads,
        mock_process_numa_cores,
        mock_process_numa_paired_threads,
        mock_process_numa_vcpu,
        mock_process_numa_memory,
        mock_process_vio_numa_nodes,
    ):
        """Process numa parameters, id, memory, vcpu exist, vim type is VIO,
        paired-threads, cores, threads do not exist in numa.
        """
        numas = [
            {"id": 0, "memory": 1, "vcpu": [1, 3]},
            {"id": 1, "memory": 2, "vcpu": [2]},
        ]
        extra_specs = {}
        expected_extra_specs = {
            "hw:numa_nodes": "2",
            "hw:cpu_sockets": "2",
        }
        self.vimconn.vim_type = "VIO"
        self.vimconn._process_numa_parameters_of_flavor(numas, extra_specs)

        self.assertEqual(mock_process_numa_memory.call_count, 2)
        self.assertEqual(mock_process_numa_vcpu.call_count, 2)
        mock_process_vio_numa_nodes.assert_called_once_with(2, {"hw:numa_nodes": "2"})
        _call_mock_process_numa_memory = mock_process_numa_memory.call_args_list
        self.assertEqual(
            _call_mock_process_numa_memory[0].args,
            (
                {"id": 0, "memory": 1, "vcpu": [1, 3]},
                0,
                {
                    "hw:numa_nodes": "2",
                },
            ),
        )
        self.assertEqual(
            _call_mock_process_numa_memory[1].args,
            (
                {"id": 1, "memory": 2, "vcpu": [2]},
                1,
                {
                    "hw:cpu_sockets": "2",
                    "hw:numa_nodes": "2",
                },
            ),
        )
        _call_mock_process_numa_vcpu = mock_process_numa_vcpu.call_args_list
        self.assertEqual(
            _call_mock_process_numa_vcpu[0].args,
            (
                {"id": 0, "memory": 1, "vcpu": [1, 3]},
                0,
                {
                    "hw:numa_nodes": "2",
                },
            ),
        )
        self.assertEqual(
            _call_mock_process_numa_vcpu[1].args,
            (
                {"id": 1, "memory": 2, "vcpu": [2]},
                1,
                {
                    "hw:cpu_sockets": "2",
                    "hw:numa_nodes": "2",
                },
            ),
        )
        self.assertDictEqual(extra_specs, expected_extra_specs)
        check_if_assert_not_called(
            [
                mock_process_numa_threads,
                mock_process_numa_cores,
                mock_process_numa_paired_threads,
            ]
        )

    @patch.object(vimconnector, "process_vio_numa_nodes", new_callable=CopyingMock())
    @patch.object(vimconnector, "process_numa_memory", new_callable=CopyingMock())
    @patch.object(vimconnector, "process_numa_vcpu", new_callable=CopyingMock())
    @patch.object(
        vimconnector,
        "process_numa_paired_threads",
        new_callable=CopyingMock(),
    )
    @patch.object(vimconnector, "process_numa_cores", new_callable=CopyingMock())
    @patch.object(vimconnector, "process_numa_threads", new_callable=CopyingMock())
    def test_process_numa_parameters_of_flavor_id_memory_vcpu_in_numa_type_openstack(
        self,
        mock_process_numa_threads,
        mock_process_numa_cores,
        mock_process_numa_paired_threads,
        mock_process_numa_vcpu,
        mock_process_numa_memory,
        mock_process_vio_numa_nodes,
    ):
        """Process numa parameters, id, memory, vcpu exist, vim type is openstack,
        paired-threads, cores, threads do not exist in numa.
        """
        numas = [
            {"id": 0, "memory": 1, "vcpu": [1, 3]},
            {"id": 1, "memory": 2, "vcpu": [2]},
        ]
        extra_specs = {}
        expected_extra_specs = {
            "hw:numa_nodes": "2",
            "hw:cpu_sockets": "2",
        }
        self.vimconn.vim_type = "openstack"
        self.vimconn._process_numa_parameters_of_flavor(numas, extra_specs)

        self.assertEqual(mock_process_numa_memory.call_count, 2)
        self.assertEqual(mock_process_numa_vcpu.call_count, 2)
        _call_mock_process_numa_memory = mock_process_numa_memory.call_args_list
        self.assertEqual(
            _call_mock_process_numa_memory[0].args,
            (
                {"id": 0, "memory": 1, "vcpu": [1, 3]},
                0,
                {"hw:numa_nodes": "2"},
            ),
        )
        self.assertEqual(
            _call_mock_process_numa_memory[1].args,
            (
                {"id": 1, "memory": 2, "vcpu": [2]},
                1,
                {"hw:cpu_sockets": "2", "hw:numa_nodes": "2"},
            ),
        )
        _call_mock_process_numa_vcpu = mock_process_numa_vcpu.call_args_list
        self.assertEqual(
            _call_mock_process_numa_vcpu[0].args,
            (
                {"id": 0, "memory": 1, "vcpu": [1, 3]},
                0,
                {"hw:numa_nodes": "2"},
            ),
        )
        self.assertEqual(
            _call_mock_process_numa_vcpu[1].args,
            (
                {"id": 1, "memory": 2, "vcpu": [2]},
                1,
                {"hw:cpu_sockets": "2", "hw:numa_nodes": "2"},
            ),
        )
        self.assertDictEqual(extra_specs, expected_extra_specs)
        check_if_assert_not_called(
            [
                mock_process_numa_threads,
                mock_process_numa_cores,
                mock_process_numa_paired_threads,
            ]
        )

    @patch.object(vimconnector, "process_vio_numa_nodes", new_callable=CopyingMock())
    @patch.object(vimconnector, "process_numa_memory", new_callable=CopyingMock())
    @patch.object(vimconnector, "process_numa_vcpu", new_callable=CopyingMock())
    @patch.object(
        vimconnector,
        "process_numa_paired_threads",
        new_callable=CopyingMock(),
    )
    @patch.object(vimconnector, "process_numa_cores", new_callable=CopyingMock())
    @patch.object(vimconnector, "process_numa_threads", new_callable=CopyingMock())
    def test_process_numa_parameters_of_flavor_id_paired_threads_in_numa_type_openstack_extra_spec_not_empty(
        self,
        mock_process_numa_threads,
        mock_process_numa_cores,
        mock_process_numa_paired_threads,
        mock_process_numa_vcpu,
        mock_process_numa_memory,
        mock_process_vio_numa_nodes,
    ):
        """Process numa parameters, id, paired-threads exist, vim type is openstack.
        vcpus calculation according to paired-threads in numa, there is extra_spec.
        ."""
        numas = [{"id": 0, "paired-threads": 3}, {"id": 1, "paired-threads": 3}]
        extra_specs = {"some-key": "some-value"}
        expected_extra_specs = {
            "hw:cpu_sockets": "2",
            "hw:cpu_threads": "12",
            "hw:numa_nodes": "2",
            "some-key": "some-value",
        }
        self.vimconn.vim_type = "openstack"
        mock_process_numa_paired_threads.side_effect = [6, 6]
        self.vimconn._process_numa_parameters_of_flavor(numas, extra_specs)

        check_if_assert_not_called([mock_process_numa_threads, mock_process_numa_cores])
        self.assertEqual(mock_process_numa_memory.call_count, 2)
        self.assertEqual(mock_process_numa_vcpu.call_count, 2)
        self.assertEqual(mock_process_numa_paired_threads.call_count, 2)
        _call_mock_process_numa_paired_threads = (
            mock_process_numa_paired_threads.call_args_list
        )
        self.assertEqual(
            _call_mock_process_numa_paired_threads[0].args,
            (
                {"id": 0, "paired-threads": 3},
                {"hw:cpu_sockets": "2", "hw:numa_nodes": "2", "some-key": "some-value"},
            ),
        )
        self.assertEqual(
            _call_mock_process_numa_paired_threads[1].args,
            (
                {"id": 1, "paired-threads": 3},
                {"hw:cpu_sockets": "2", "hw:numa_nodes": "2", "some-key": "some-value"},
            ),
        )
        self.assertDictEqual(extra_specs, expected_extra_specs)

    @patch.object(vimconnector, "process_vio_numa_nodes", new_callable=CopyingMock())
    @patch.object(vimconnector, "process_numa_memory", new_callable=CopyingMock())
    @patch.object(vimconnector, "process_numa_vcpu", new_callable=CopyingMock())
    @patch.object(
        vimconnector,
        "process_numa_paired_threads",
        new_callable=CopyingMock(),
    )
    @patch.object(vimconnector, "process_numa_cores", new_callable=CopyingMock())
    @patch.object(vimconnector, "process_numa_threads", new_callable=CopyingMock())
    def test_process_numa_parameters_of_flavor_id_paired_threads_in_numa_type_vio_extra_spec_not_empty(
        self,
        mock_process_numa_threads,
        mock_process_numa_cores,
        mock_process_numa_paired_threads,
        mock_process_numa_vcpu,
        mock_process_numa_memory,
        mock_process_vio_numa_nodes,
    ):
        """Process numa parameters, id, paired-threads exist, vim type is VIO.
        vcpus calculation according to paired-threads in numa, there is extra_spec.
        """
        numas = [{"id": 0, "paired-threads": 2}, {"id": 1, "paired-threads": 2}]
        extra_specs = {"some-key": "some-value"}
        expected_extra_specs = {
            "hw:numa_nodes": "2",
            "hw:cpu_sockets": "2",
            "hw:cpu_threads": "8",
            "some-key": "some-value",
        }
        self.vimconn.vim_type = "VIO"
        mock_process_numa_paired_threads.side_effect = [4, 4]
        self.vimconn._process_numa_parameters_of_flavor(numas, extra_specs)
        check_if_assert_not_called([mock_process_numa_threads, mock_process_numa_cores])
        self.assertEqual(mock_process_numa_paired_threads.call_count, 2)
        self.assertEqual(mock_process_numa_memory.call_count, 2)
        self.assertEqual(mock_process_numa_vcpu.call_count, 2)
        _call_mock_process_numa_paired_threads = (
            mock_process_numa_paired_threads.call_args_list
        )
        mock_process_vio_numa_nodes.assert_called_once_with(
            2, {"some-key": "some-value", "hw:numa_nodes": "2"}
        )
        self.assertEqual(
            _call_mock_process_numa_paired_threads[0].args,
            (
                {"id": 0, "paired-threads": 2},
                {
                    "hw:cpu_sockets": "2",
                    "hw:numa_nodes": "2",
                    "some-key": "some-value",
                },
            ),
        )
        self.assertEqual(
            _call_mock_process_numa_paired_threads[1].args,
            (
                {"id": 1, "paired-threads": 2},
                {
                    "hw:cpu_sockets": "2",
                    "hw:numa_nodes": "2",
                    "some-key": "some-value",
                },
            ),
        )
        self.assertDictEqual(extra_specs, expected_extra_specs)

    @patch.object(vimconnector, "process_vio_numa_nodes", new_callable=CopyingMock())
    @patch.object(vimconnector, "process_numa_memory", new_callable=CopyingMock())
    @patch.object(vimconnector, "process_numa_vcpu", new_callable=CopyingMock())
    @patch.object(
        vimconnector,
        "process_numa_paired_threads",
        new_callable=CopyingMock(),
    )
    @patch.object(vimconnector, "process_numa_cores", new_callable=CopyingMock())
    @patch.object(vimconnector, "process_numa_threads", new_callable=CopyingMock())
    def test_process_numa_parameters_of_flavor_id_cores_in_numa_type_openstack(
        self,
        mock_process_numa_threads,
        mock_process_numa_cores,
        mock_process_numa_paired_threads,
        mock_process_numa_vcpu,
        mock_process_numa_memory,
        mock_process_vio_numa_nodes,
    ):
        """Process numa parameters, id, cores exist, vim type is openstack.
        vcpus calculation according to cores in numa.
        """
        numas = [{"id": 0, "cores": 1}, {"id": 1, "cores": 2}]
        extra_specs = {}
        updated_extra_specs = {"hw:numa_nodes": "2", "hw:cpu_sockets": "2"}
        expected_extra_specs = {
            "hw:numa_nodes": "2",
            "hw:cpu_sockets": "2",
            "hw:cpu_cores": "3",
        }
        self.vimconn.vim_type = "openstack"
        mock_process_numa_cores.side_effect = [1, 2]
        self.vimconn._process_numa_parameters_of_flavor(numas, extra_specs)

        check_if_assert_not_called(
            [mock_process_numa_threads, mock_process_numa_paired_threads]
        )
        self.assertEqual(mock_process_numa_cores.call_count, 2)
        self.assertEqual(mock_process_numa_memory.call_count, 2)
        self.assertEqual(mock_process_numa_vcpu.call_count, 2)
        _call_mock_process_numa_cores = mock_process_numa_cores.call_args_list
        self.assertEqual(
            _call_mock_process_numa_cores[0].args,
            ({"id": 0, "cores": 1}, updated_extra_specs),
        )
        self.assertEqual(
            _call_mock_process_numa_cores[1].args,
            ({"id": 1, "cores": 2}, updated_extra_specs),
        )
        self.assertDictEqual(extra_specs, expected_extra_specs)

    @patch.object(vimconnector, "process_vio_numa_nodes", new_callable=CopyingMock())
    @patch.object(vimconnector, "process_numa_memory", new_callable=CopyingMock())
    @patch.object(vimconnector, "process_numa_vcpu", new_callable=CopyingMock())
    @patch.object(
        vimconnector,
        "process_numa_paired_threads",
        new_callable=CopyingMock(),
    )
    @patch.object(vimconnector, "process_numa_cores", new_callable=CopyingMock())
    @patch.object(vimconnector, "process_numa_threads", new_callable=CopyingMock())
    def test_process_numa_parameters_of_flavor_id_cores_in_numa_type_vio(
        self,
        mock_process_numa_threads,
        mock_process_numa_cores,
        mock_process_numa_paired_threads,
        mock_process_numa_vcpu,
        mock_process_numa_memory,
        mock_process_vio_numa_nodes,
    ):
        """Process numa parameters, id, cores exist, vim type is VIO.
        vcpus calculation according to cores in numa.
        """
        numas = [{"id": 0, "cores": 1}, {"id": 1, "cores": 2}]
        extra_specs = {}
        expected_extra_specs = {
            "hw:cpu_cores": "3",
            "hw:cpu_sockets": "2",
            "hw:numa_nodes": "2",
        }
        self.vimconn.vim_type = "VIO"
        mock_process_numa_cores.side_effect = [1, 2]
        self.vimconn._process_numa_parameters_of_flavor(numas, extra_specs)
        check_if_assert_not_called(
            [mock_process_numa_threads, mock_process_numa_paired_threads]
        )
        self.assertEqual(mock_process_numa_memory.call_count, 2)
        self.assertEqual(mock_process_numa_vcpu.call_count, 2)
        self.assertEqual(mock_process_numa_cores.call_count, 2)
        mock_process_vio_numa_nodes.assert_called_once_with(2, {"hw:numa_nodes": "2"})
        _call_mock_process_numa_cores = mock_process_numa_cores.call_args_list
        self.assertEqual(
            _call_mock_process_numa_cores[0].args,
            (
                {"id": 0, "cores": 1},
                {
                    "hw:cpu_sockets": "2",
                    "hw:numa_nodes": "2",
                },
            ),
        )
        self.assertEqual(
            _call_mock_process_numa_cores[1].args,
            (
                {"id": 1, "cores": 2},
                {
                    "hw:cpu_sockets": "2",
                    "hw:numa_nodes": "2",
                },
            ),
        )
        self.assertDictEqual(extra_specs, expected_extra_specs)

    @patch.object(vimconnector, "process_vio_numa_nodes", new_callable=CopyingMock())
    @patch.object(vimconnector, "process_numa_memory", new_callable=CopyingMock())
    @patch.object(vimconnector, "process_numa_vcpu", new_callable=CopyingMock())
    @patch.object(
        vimconnector,
        "process_numa_paired_threads",
        new_callable=CopyingMock(),
    )
    @patch.object(vimconnector, "process_numa_cores", new_callable=CopyingMock())
    @patch.object(vimconnector, "process_numa_threads", new_callable=CopyingMock())
    def test_process_numa_parameters_of_flavor_without_numa_id_with_threads_type_vio(
        self,
        mock_process_numa_threads,
        mock_process_numa_cores,
        mock_process_numa_paired_threads,
        mock_process_numa_vcpu,
        mock_process_numa_memory,
        mock_process_vio_numa_nodes,
    ):
        """Process numa parameters, memory, vcpu, thread exist, vim type is VIO,
        vcpus calculation according threads in numa, there are not numa ids.
        """
        numas = [
            {"memory": 1, "vcpu": [1, 3], "threads": 3},
            {"memory": 2, "vcpu": [2]},
        ]
        extra_specs = {}
        expected_extra_specs = {
            "hw:numa_nodes": "2",
            "hw:cpu_sockets": "2",
            "hw:cpu_threads": "3",
        }
        self.vimconn.vim_type = "VIO"
        mock_process_numa_threads.return_value = 3
        self.vimconn._process_numa_parameters_of_flavor(numas, extra_specs)
        check_if_assert_not_called(
            [
                mock_process_numa_memory,
                mock_process_numa_vcpu,
                mock_process_numa_cores,
                mock_process_numa_paired_threads,
            ]
        )
        mock_process_vio_numa_nodes.assert_called_once_with(2, {"hw:numa_nodes": "2"})
        self.assertEqual(mock_process_numa_threads.call_count, 1)
        _call_mock_process_numa_threads = mock_process_numa_threads.call_args_list
        self.assertEqual(
            _call_mock_process_numa_threads[0].args,
            (
                {"memory": 1, "vcpu": [1, 3], "threads": 3},
                {
                    "hw:cpu_sockets": "2",
                    "hw:numa_nodes": "2",
                },
            ),
        )
        self.assertDictEqual(extra_specs, expected_extra_specs)

    @patch.object(vimconnector, "process_vio_numa_nodes", new_callable=CopyingMock())
    @patch.object(vimconnector, "process_numa_memory", new_callable=CopyingMock())
    @patch.object(vimconnector, "process_numa_vcpu", new_callable=CopyingMock())
    @patch.object(
        vimconnector,
        "process_numa_paired_threads",
        new_callable=CopyingMock(autospec=True),
    )
    @patch.object(vimconnector, "process_numa_cores", new_callable=CopyingMock())
    @patch.object(vimconnector, "process_numa_threads", new_callable=CopyingMock())
    def test_process_numa_parameters_of_flavor_without_numa_id_with_threads_type_openstack(
        self,
        mock_process_numa_threads,
        mock_process_numa_cores,
        mock_process_numa_paired_threads,
        mock_process_numa_vcpu,
        mock_process_numa_memory,
        mock_process_vio_numa_nodes,
    ):
        """Process numa parameters, memory, vcpu, thread exist, vim type is openstack,
        vcpus calculation according threads in numa, there are not numa ids.
        """
        numas = [
            {"memory": 1, "vcpu": [1, 3], "threads": 3},
            {"memory": 2, "vcpu": [2]},
        ]
        extra_specs = {}
        expected_extra_specs = {
            "hw:numa_nodes": "2",
            "hw:cpu_sockets": "2",
            "hw:cpu_threads": "3",
        }
        self.vimconn.vim_type = "openstack"
        mock_process_numa_threads.return_value = 3
        self.vimconn._process_numa_parameters_of_flavor(numas, extra_specs)

        check_if_assert_not_called(
            [
                mock_process_numa_memory,
                mock_process_numa_vcpu,
                mock_process_numa_cores,
                mock_process_numa_paired_threads,
                mock_process_vio_numa_nodes,
            ]
        )
        self.assertEqual(mock_process_numa_threads.call_count, 1)
        _call_mock_process_numa_threads = mock_process_numa_threads.call_args_list
        self.assertEqual(
            _call_mock_process_numa_threads[0].args,
            (
                {"memory": 1, "vcpu": [1, 3], "threads": 3},
                {"hw:cpu_sockets": "2", "hw:numa_nodes": "2"},
            ),
        )
        self.assertDictEqual(extra_specs, expected_extra_specs)

    @patch.object(vimconnector, "process_vio_numa_nodes", new_callable=CopyingMock())
    @patch.object(vimconnector, "process_numa_memory", new_callable=CopyingMock())
    @patch.object(vimconnector, "process_numa_vcpu", new_callable=CopyingMock())
    @patch.object(
        vimconnector,
        "process_numa_paired_threads",
        new_callable=CopyingMock(),
    )
    @patch.object(vimconnector, "process_numa_cores", new_callable=CopyingMock())
    @patch.object(vimconnector, "process_numa_threads", new_callable=CopyingMock())
    def test_process_numa_parameters_of_flavor_empty_numas_list_type_vio(
        self,
        mock_process_numa_threads,
        mock_process_numa_cores,
        mock_process_numa_paired_threads,
        mock_process_numa_vcpu,
        mock_process_numa_memory,
        mock_process_vio_numa_nodes,
    ):
        """Numa list is empty, vim type is VIO."""
        numas = []
        extra_specs = {}
        expected_extra_specs = {"hw:numa_nodes": "0"}
        self.vimconn.vim_type = "VIO"
        self.vimconn._process_numa_parameters_of_flavor(numas, extra_specs)
        check_if_assert_not_called(
            [
                mock_process_numa_memory,
                mock_process_numa_vcpu,
                mock_process_numa_cores,
                mock_process_numa_paired_threads,
                mock_process_numa_threads,
            ]
        )
        mock_process_vio_numa_nodes.assert_called_once_with(0, {"hw:numa_nodes": "0"})
        self.assertDictEqual(extra_specs, expected_extra_specs)

    @patch.object(vimconnector, "process_vio_numa_nodes", new_callable=CopyingMock())
    @patch.object(vimconnector, "process_numa_memory", new_callable=CopyingMock())
    @patch.object(vimconnector, "process_numa_vcpu", new_callable=CopyingMock())
    @patch.object(
        vimconnector,
        "process_numa_paired_threads",
        new_callable=CopyingMock(),
    )
    @patch.object(vimconnector, "process_numa_cores", new_callable=CopyingMock())
    @patch.object(vimconnector, "process_numa_threads", new_callable=CopyingMock())
    def test_process_numa_parameters_of_flavor_empty_numas_list_type_openstack(
        self,
        mock_process_numa_threads,
        mock_process_numa_cores,
        mock_process_numa_paired_threads,
        mock_process_numa_vcpu,
        mock_process_numa_memory,
        mock_process_vio_numa_nodes,
    ):
        """Numa list is empty, vim type is openstack."""
        numas = []
        extra_specs = {}
        expected_extra_specs = {"hw:numa_nodes": "0"}
        self.vimconn.vim_type = "openstack"
        mock_process_numa_threads.return_value = None
        self.vimconn._process_numa_parameters_of_flavor(numas, extra_specs)

        check_if_assert_not_called(
            [
                mock_process_numa_memory,
                mock_process_numa_vcpu,
                mock_process_numa_cores,
                mock_process_numa_paired_threads,
                mock_process_numa_threads,
                mock_process_vio_numa_nodes,
            ]
        )
        self.assertDictEqual(extra_specs, expected_extra_specs)

    def test_process_numa_memory_empty_extra_spec(self):
        numa = {"memory": 2, "vcpu": [2]}
        node_id = 2
        extra_specs = {}
        expected_extra_spec = {"hw:numa_mem.2": 2048}
        self.vimconn.process_numa_memory(numa, node_id, extra_specs)
        self.assertDictEqual(extra_specs, expected_extra_spec)

    def test_process_numa_memory_not_exist(self):
        numa = {"vcpu": [2]}
        node_id = 2
        extra_specs = {"vmware:latency_sensitivity_level": "high"}
        self.vimconn.process_numa_memory(numa, node_id, extra_specs)
        self.assertDictEqual(extra_specs, {"vmware:latency_sensitivity_level": "high"})

    def test_process_numa_memory_node_id_is_none(self):
        numa = {"memory": 2, "vcpu": [2]}
        node_id = None
        extra_specs = {}
        expected_extra_spec = {"hw:numa_mem.None": 2048}
        self.vimconn.process_numa_memory(numa, node_id, extra_specs)
        self.assertDictEqual(extra_specs, expected_extra_spec)

    def test_process_numa_vcpu_empty_extra_spec(self):
        numa = {"vcpu": [2]}
        node_id = 0
        extra_specs = {}
        expected_extra_spec = {"hw:numa_cpus.0": "2"}
        self.vimconn.process_numa_vcpu(numa, node_id, extra_specs)
        self.assertDictEqual(extra_specs, expected_extra_spec)

    def test_process_numa_vcpu_not_exist(self):
        numa = {"memory": 2}
        node_id = 0
        extra_specs = {"vmware:latency_sensitivity_level": "high"}
        expected_extra_spec = {"vmware:latency_sensitivity_level": "high"}
        self.vimconn.process_numa_vcpu(numa, node_id, extra_specs)
        self.assertDictEqual(extra_specs, expected_extra_spec)

    def test_process_numa_vcpu_empty_node_id(self):
        numa = {"vcpu": [2]}
        node_id = ""
        extra_specs = {}
        expected_extra_spec = {"hw:numa_cpus.": "2"}
        self.vimconn.process_numa_vcpu(numa, node_id, extra_specs)
        self.assertDictEqual(extra_specs, expected_extra_spec)

    def test_process_numa_vcpu_empty_numa_dict(self):
        numa = {}
        node_id = 4
        extra_specs = {}
        self.vimconn.process_numa_vcpu(numa, node_id, extra_specs)
        self.assertDictEqual(extra_specs, {})

    def test_process_numa_vcpu_str_node_id(self):
        numa = {"vcpu": [2]}
        node_id = "12"
        extra_specs = {}
        expected_extra_spec = {"hw:numa_cpus.12": "2"}
        self.vimconn.process_numa_vcpu(numa, node_id, extra_specs)
        self.assertDictEqual(extra_specs, expected_extra_spec)

    def test_process_numa_paired_threads_empty_extra_spec(self):
        numa = {"id": 0, "paired-threads": 3}
        extra_specs = {}
        expected_extra_spec = {
            "hw:cpu_thread_policy": "require",
            "hw:cpu_policy": "dedicated",
        }
        result = self.vimconn.process_numa_paired_threads(numa, extra_specs)
        self.assertDictEqual(extra_specs, expected_extra_spec)
        self.assertEqual(result, 6)

    def test_process_numa_paired_threads_empty_numa(self):
        numa = {}
        extra_specs = {}
        result = self.vimconn.process_numa_paired_threads(numa, extra_specs)
        self.assertDictEqual(extra_specs, {})
        self.assertEqual(result, None)

    def test_process_numa_paired_threads_not_exist(self):
        numa = {"vcpu": [2]}
        extra_specs = {}
        result = self.vimconn.process_numa_paired_threads(numa, extra_specs)
        self.assertDictEqual(extra_specs, {})
        self.assertEqual(result, None)

    def test_process_numa_paired_threads_str_thread_num(self):
        numa = {"id": 0, "paired-threads": "3"}
        extra_specs = {}
        expected_extra_spec = {
            "hw:cpu_thread_policy": "require",
            "hw:cpu_policy": "dedicated",
        }
        result = self.vimconn.process_numa_paired_threads(numa, extra_specs)
        self.assertDictEqual(extra_specs, expected_extra_spec)
        self.assertEqual(result, "33")

    def test_process_numa_paired_threads_none_thread_num(self):
        numa = {"id": 0, "paired-threads": None}
        extra_specs = {}
        result = self.vimconn.process_numa_paired_threads(numa, extra_specs)
        self.assertDictEqual(extra_specs, {})
        self.assertEqual(result, None)

    def test_process_numa_cores_empty_extra_spec(self):
        numa = {"id": 0, "cores": 1}
        extra_specs = {}
        expected_extra_spec = {
            "hw:cpu_policy": "dedicated",
            "hw:cpu_thread_policy": "isolate",
        }
        result = self.vimconn.process_numa_cores(numa, extra_specs)
        self.assertDictEqual(extra_specs, expected_extra_spec)
        self.assertEqual(result, 1)

    def test_process_numa_cores_not_exist(self):
        numa = {"id": 0, "paired-threads": 3}
        extra_specs = {}
        result = self.vimconn.process_numa_cores(numa, extra_specs)
        self.assertDictEqual(extra_specs, {})
        self.assertEqual(result, None)

    def test_process_numa_cores_empty_numa(self):
        numa = {}
        extra_specs = expected_extra_spec = {"some-key": "some-val"}
        result = self.vimconn.process_numa_cores(numa, extra_specs)
        self.assertDictEqual(extra_specs, expected_extra_spec)
        self.assertEqual(result, None)

    def test_process_numa_cores_none_core_num(self):
        numa = {"memory": 1, "cores": None}
        extra_specs = {}
        result = self.vimconn.process_numa_cores(numa, extra_specs)
        self.assertDictEqual(extra_specs, {})
        self.assertEqual(result, None)

    def test_process_numa_cores_string_core_num(self):
        numa = {"id": 0, "cores": "1"}
        extra_specs = {"some-key": "some-val"}
        expected_extra_spec = {
            "hw:cpu_policy": "dedicated",
            "hw:cpu_thread_policy": "isolate",
            "some-key": "some-val",
        }
        result = self.vimconn.process_numa_cores(numa, extra_specs)
        self.assertDictEqual(extra_specs, expected_extra_spec)
        self.assertEqual(result, "1")

    def test_process_numa_cores_float_core_num(self):
        numa = {"memory": 2, "cores": 10.03}
        extra_specs = {"some-key": "some-val"}
        expected_extra_spec = {
            "hw:cpu_policy": "dedicated",
            "hw:cpu_thread_policy": "isolate",
            "some-key": "some-val",
        }
        result = self.vimconn.process_numa_cores(numa, extra_specs)
        self.assertDictEqual(extra_specs, expected_extra_spec)
        self.assertEqual(result, 10.03)

    def test_process_numa_threads_empty_extra_spec_int_thread_num(self):
        numa = {"memory": 1, "vcpu": [1, 3], "threads": 3}
        extra_specs = {}
        expected_extra_spec = {
            "hw:cpu_policy": "dedicated",
            "hw:cpu_thread_policy": "prefer",
        }
        result = self.vimconn.process_numa_threads(numa, extra_specs)
        self.assertDictEqual(extra_specs, expected_extra_spec)
        self.assertEqual(result, 3)

    def test_process_numa_threads_empty_numa(self):
        numa = {}
        extra_specs = {"some-key": "some-val"}
        expected_extra_spec = {"some-key": "some-val"}
        result = self.vimconn.process_numa_threads(numa, extra_specs)
        self.assertDictEqual(extra_specs, expected_extra_spec)
        self.assertEqual(result, None)

    def test_process_numa_threads_not_exist(self):
        numa = {"memory": 1}
        extra_specs = expected_extra_spec = {"some-key": "some-val"}
        result = self.vimconn.process_numa_threads(numa, extra_specs)
        self.assertDictEqual(extra_specs, expected_extra_spec)
        self.assertEqual(result, None)

    def test_process_numa_threads_str_thread_num(self):
        numa = {"vcpu": [1, 3], "threads": "3"}
        extra_specs = {}
        expected_extra_spec = {
            "hw:cpu_policy": "dedicated",
            "hw:cpu_thread_policy": "prefer",
        }
        result = self.vimconn.process_numa_threads(numa, extra_specs)
        self.assertDictEqual(extra_specs, expected_extra_spec)
        self.assertEqual(result, "3")

    def test_process_numa_threads_none_thread_num(self):
        numa = {"vcpu": [1, 3], "threads": None}
        extra_specs = {}
        result = self.vimconn.process_numa_threads(numa, extra_specs)
        self.assertDictEqual(extra_specs, {})
        self.assertEqual(result, None)

    def test_process_numa_threads_float_thread_num(self):
        numa = {"memory": 1, "vcpu": [1, 3], "threads": 3.3}
        extra_specs = {"some-key": "some-val"}
        expected_extra_spec = {
            "hw:cpu_policy": "dedicated",
            "hw:cpu_thread_policy": "prefer",
            "some-key": "some-val",
        }
        result = self.vimconn.process_numa_threads(numa, extra_specs)
        self.assertDictEqual(extra_specs, expected_extra_spec)
        self.assertEqual(result, 3.3)

    def test_change_the_flavor_name_not_existing_name(self):
        """Flavor name does not exist in Openstack flavor list."""
        self.flavor1.name = "sample-flavor-3"
        self.flavor2.name = "other-flavor-4"
        self.vimconn.nova.flavors.list.return_value = [self.flavor1, self.flavor2]
        name = "other-flavor-3"
        name_suffix = 3
        flavor_data = {"name": "other-flavor"}
        result = self.vimconn._change_flavor_name(name, name_suffix, flavor_data)
        self.assertEqual(result, name)
        self.vimconn.nova.flavors.list.assert_called_once()
        # Checking whether name_suffix changed or not.
        self.assertEqual(name_suffix, 3)

    def test_change_the_flavor_name_existing_name(self):
        """Flavor name exists in Openstack flavor list."""
        self.flavor1.name = "other-flavor-6"
        self.flavor2.name = "other-flavor-3"
        self.vimconn.nova.flavors.list.return_value = [self.flavor1, self.flavor2]
        name = "other-flavor-3"
        name_suffix = 5
        flavor_data = {"name": "other-flavor"}
        expected_result = "other-flavor-7"
        result = self.vimconn._change_flavor_name(name, name_suffix, flavor_data)
        self.assertEqual(result, expected_result)
        # Checking whether name_suffix changed or not.
        self.assertEqual(name_suffix, 5)
        self.vimconn.nova.flavors.list.assert_called_once()

    def test_change_the_flavor_name_flavor_data_does_not_have_name(self):
        """Flavor data does not have name."""
        self.flavor1.name = "other-flavor-6"
        self.flavor2.name = "other-flavor-3"
        self.vimconn.nova.flavors.list.return_value = [self.flavor1, self.flavor2]
        name = "other-flavor-3"
        name_suffix = 5
        flavor_data = {}
        with self.assertRaises(KeyError):
            self.vimconn._change_flavor_name(name, name_suffix, flavor_data)
        self.vimconn.nova.flavors.list.assert_called_once()
        # Checking whether name_suffix changed or not.
        self.assertEqual(name_suffix, 5)

    def test_change_the_flavor_name_invalid_name_suffix(self):
        """Name suffix is invalid."""
        self.flavor1.name = "other-flavor-6"
        self.flavor2.name = "other-flavor-3"
        self.vimconn.nova.flavors.list.return_value = [self.flavor1, self.flavor2]
        name = "other-flavor-3"
        name_suffix = "a"
        flavor_data = {"name": "other-flavor"}
        with self.assertRaises(TypeError):
            self.vimconn._change_flavor_name(name, name_suffix, flavor_data)
        self.vimconn.nova.flavors.list.assert_called_once()
        # Checking whether name_suffix changed or not.
        self.assertEqual(name_suffix, "a")

    def test_change_the_flavor_name_given_name_is_empty(self):
        """Given name is empty string."""
        self.flavor1.name = "other-flavor-6"
        self.flavor2.name = "other-flavor-3"
        self.vimconn.nova.flavors.list.return_value = [self.flavor1, self.flavor2]
        name = ""
        name_suffix = 3
        flavor_data = {"name": "other-flavor"}
        result = self.vimconn._change_flavor_name(name, name_suffix, flavor_data)
        self.assertEqual(result, "")
        self.vimconn.nova.flavors.list.assert_called_once()
        # Checking whether name_suffix increased or not.
        self.assertEqual(name_suffix, 3)

    def test_change_the_flavor_name_given_name_is_none(self):
        """Given name is None."""
        self.flavor1.name = "other-flavor-6"
        self.flavor2.name = "other-flavor-3"
        self.vimconn.nova.flavors.list.return_value = [self.flavor1, self.flavor2]
        name = None
        name_suffix = 6
        flavor_data = {"name": "other-flavor"}
        result = self.vimconn._change_flavor_name(name, name_suffix, flavor_data)
        self.assertEqual(result, None)
        self.vimconn.nova.flavors.list.assert_called_once()
        # Checking whether name_suffix increased or not.
        self.assertEqual(name_suffix, 6)

    def test_change_the_flavor_name_empty_nova_flavor_list(self):
        """Nova flavor list is empty."""
        self.vimconn.nova.flavors.list.return_value = []
        name = "other-flavor-3"
        name_suffix = 5
        flavor_data = {"name": "other-flavor"}
        result = self.vimconn._change_flavor_name(name, name_suffix, flavor_data)
        self.vimconn.nova.flavors.list.assert_called_once()
        self.assertEqual(result, name)
        # Checking whether name_suffix increased or not.
        self.assertEqual(name_suffix, 5)

    @patch.object(
        vimconnector,
        "_process_numa_parameters_of_flavor",
        new_callable=CopyingMock(),
    )
    @patch.object(vimconnector, "process_resource_quota", new_callable=CopyingMock())
    def test_process_extended_config_of_flavor_with_numa_cpu_mem_vif_disk_quota(
        self, mock_process_resource_quota, mock_process_numa_parameters_of_flavor
    ):
        """Process extended config, extended has numas, cpu, mem, vif and disk-io quota."""
        numas = [
            {"memory": 1, "vcpu": [1, 3], "threads": 3},
            {"memory": 2, "vcpu": [2]},
        ]
        extended = {
            "numas": numas,
            "cpu-quota": {"limit": 3},
            "mem-quota": {"limit": 1},
            "vif-quota": {"limit": 10},
            "disk-io-quota": {"limit": 50},
            "mempage-size": "LARGE",
        }
        extra_specs = {}
        expected_extra_specs = {
            "hw:mem_page_size": "large",
        }
        self.vimconn._process_extended_config_of_flavor(extended, extra_specs)

        self.assertEqual(mock_process_resource_quota.call_count, 4)
        mock_process_numa_parameters_of_flavor.assert_called_once_with(numas, {})
        self.assertEqual(extra_specs, expected_extra_specs)

    @patch.object(
        vimconnector,
        "_process_numa_parameters_of_flavor",
        new_callable=CopyingMock(),
    )
    @patch.object(vimconnector, "process_resource_quota", new_callable=CopyingMock())
    def test_process_extended_config_of_flavor_with_numa_wrong_disk_quota(
        self, mock_process_resource_quota, mock_process_numa_parameters_of_flavor
    ):
        """Process extended config, extended has wrong disk quota key."""
        numas = [
            {"memory": 1, "threads": 3},
            {"memory": 2, "vcpu": [2]},
        ]
        extended = {
            "numas": numas,
            "disk-quota": {"limit": 50},
            "mempage-size": "PREFER_LARGE",
        }
        extra_specs = {}
        expected_extra_specs = {
            "hw:mem_page_size": "any",
        }
        self.vimconn._process_extended_config_of_flavor(extended, extra_specs)
        mock_process_resource_quota.assert_not_called()
        mock_process_numa_parameters_of_flavor.assert_called_once_with(numas, {})
        self.assertEqual(extra_specs, expected_extra_specs)

    @patch.object(
        vimconnector,
        "_process_numa_parameters_of_flavor",
        new_callable=CopyingMock(),
    )
    @patch.object(vimconnector, "process_resource_quota", new_callable=CopyingMock())
    def test_process_extended_config_of_flavor_without_numa_cpu_mem_vif_disk_quota(
        self, mock_process_resource_quota, mock_process_numa_parameters_of_flavor
    ):
        """Process extended config, extended has cpu, mem, vif and disk-io quota but not numas."""
        extended = {
            "cpu-quota": {"limit": 3},
            "mem-quota": {"limit": 1},
            "vif-quota": {"limit": 10},
            "disk-io-quota": {"limit": 50},
            "mempage-size": "SMALL",
        }
        extra_specs = {}
        expected_extra_specs = {
            "hw:mem_page_size": "small",
        }
        self.vimconn._process_extended_config_of_flavor(extended, extra_specs)
        self.assertEqual(mock_process_resource_quota.call_count, 4)
        mock_process_numa_parameters_of_flavor.assert_not_called()
        self.assertEqual(extra_specs, expected_extra_specs)

    @patch.object(
        vimconnector,
        "_process_numa_parameters_of_flavor",
        new_callable=CopyingMock(),
    )
    @patch.object(vimconnector, "process_resource_quota", new_callable=CopyingMock())
    def test_process_extended_config_of_flavor_with_numa_with_cpu_pinning_mem_policy(
        self, mock_process_resource_quota, mock_process_numa_parameters_of_flavor
    ):
        """Process extended config, extended has cpu, mem quota, cpu-pinning and mem-policy."""
        numas = [
            {"memory": 1},
            {"memory": 2, "vcpu": [2]},
        ]
        extended = {
            "numas": numas,
            "cpu-quota": {"limit": 3},
            "mem-quota": {"limit": 1},
            "mempage-size": "LARGE",
            "cpu-pinning-policy": "DEDICATED",
            "mem-policy": "STRICT",
        }
        extra_specs = {}
        expected_extra_specs = {
            "hw:mem_page_size": "large",
            "hw:cpu_policy": "dedicated",
            "hw:numa_mempolicy": "strict",
        }
        self.vimconn._process_extended_config_of_flavor(extended, extra_specs)
        self.assertEqual(mock_process_resource_quota.call_count, 2)
        mock_process_numa_parameters_of_flavor.assert_called_once_with(numas, {})
        self.assertEqual(extra_specs, expected_extra_specs)

    @patch.object(
        vimconnector,
        "_process_numa_parameters_of_flavor",
        new_callable=CopyingMock(),
    )
    @patch.object(vimconnector, "process_resource_quota", new_callable=CopyingMock())
    def test_process_extended_config_of_flavor_without_numa_with_cpu_pinning_mem_policy(
        self, mock_process_resource_quota, mock_process_numa_parameters_of_flavor
    ):
        """Process extended config, extended has cpu, mem quota, cpu-pinning and mem-policy but not numas."""
        extended = {
            "cpu-quota": {"limit": 3},
            "mem-quota": {"limit": 1},
            "mempage-size": "LARGE",
            "cpu-pinning-policy": "DEDICATED",
            "mem-policy": "STRICT",
        }
        extra_specs = {}
        expected_extra_specs = {
            "hw:mem_page_size": "large",
            "hw:cpu_policy": "dedicated",
            "hw:numa_mempolicy": "strict",
        }
        self.vimconn._process_extended_config_of_flavor(extended, extra_specs)
        self.assertEqual(mock_process_resource_quota.call_count, 2)
        mock_process_numa_parameters_of_flavor.assert_not_called()
        self.assertEqual(extra_specs, expected_extra_specs)

    @patch.object(
        vimconnector,
        "_process_numa_parameters_of_flavor",
        new_callable=CopyingMock(),
    )
    @patch.object(vimconnector, "process_resource_quota", new_callable=CopyingMock())
    def test_process_extended_config_of_flavor_without_numa_with_wrong_mempage_size(
        self, mock_process_resource_quota, mock_process_numa_parameters_of_flavor
    ):
        """Process extended config, extended has wrong mempage-size without numas."""
        extended = {
            "cpu-quota": {"limit": 3},
            "mem-quota": {"limit": 1},
            "mempage-size": "SIZE_2GB",
            "cpu-pinning-policy": "DEDICATED",
            "mem-policy": "STRICT",
        }
        extra_specs = {}

        expected_extra_specs = {
            "hw:cpu_policy": "dedicated",
            "hw:numa_mempolicy": "strict",
        }
        self.vimconn._process_extended_config_of_flavor(extended, extra_specs)
        self.assertEqual(mock_process_resource_quota.call_count, 2)
        mock_process_numa_parameters_of_flavor.assert_not_called()
        self.assertEqual(extra_specs, expected_extra_specs)

    @patch.object(
        vimconnector,
        "_process_numa_parameters_of_flavor",
        new_callable=CopyingMock(),
    )
    @patch.object(vimconnector, "process_resource_quota", new_callable=CopyingMock())
    def test_process_extended_config_of_flavor_with_numa_with_wrong_mempage_size(
        self, mock_process_resource_quota, mock_process_numa_parameters_of_flavor
    ):
        """Process extended config, extended has wrong mempage-size with numas."""
        numas = [
            {"memory": 1},
            {"memory": 2, "vcpu": [2]},
        ]
        extended = {
            "numas": numas,
            "cpu-quota": {"limit": 3},
            "mem-quota": {"limit": 1},
            "mempage-size": "SIZE_2GB",
            "cpu-pinning-policy": "DEDICATED",
            "mem-policy": "STRICT",
        }
        extra_specs = {}
        expected_extra_specs = {
            "hw:cpu_policy": "dedicated",
            "hw:numa_mempolicy": "strict",
        }
        self.vimconn._process_extended_config_of_flavor(extended, extra_specs)
        self.assertEqual(mock_process_resource_quota.call_count, 2)
        mock_process_numa_parameters_of_flavor.assert_called_once_with(numas, {})
        self.assertEqual(extra_specs, expected_extra_specs)

    @patch.object(
        vimconnector,
        "_process_numa_parameters_of_flavor",
        new_callable=CopyingMock(),
    )
    @patch.object(vimconnector, "process_resource_quota", new_callable=CopyingMock())
    def test_process_extended_config_of_flavor_none_vcpus(
        self, mock_process_resource_quota, mock_process_numa_parameters_of_flavor
    ):
        """Process extended config, extended has cpu, mem quota, cpu-pinning and mem-policy, vcpus is None."""
        numas = [
            {"memory": 1},
            {"memory": 2, "vcpu": [2]},
        ]
        extended = {
            "numas": numas,
            "cpu-quota": {"limit": 3},
            "mem-quota": {"limit": 1},
            "mempage-size": "SIZE_2GB",
            "cpu-pinning-policy": "DEDICATED",
            "mem-policy": "STRICT",
        }
        extra_specs = {}
        expected_extra_specs = {
            "hw:cpu_policy": "dedicated",
            "hw:numa_mempolicy": "strict",
        }
        self.vimconn._process_extended_config_of_flavor(extended, extra_specs)
        self.assertEqual(mock_process_resource_quota.call_count, 2)
        mock_process_numa_parameters_of_flavor.assert_called_once_with(numas, {})
        self.assertEqual(extra_specs, expected_extra_specs)

    @patch.object(
        vimconnector,
        "_process_numa_parameters_of_flavor",
        new_callable=CopyingMock(),
    )
    @patch.object(vimconnector, "process_resource_quota", new_callable=CopyingMock())
    def test_process_extended_config_of_flavor_none_vcpus_without_numas(
        self, mock_process_resource_quota, mock_process_numa_parameters_of_flavor
    ):
        """Process extended config, extended has cpu, mem quota, cpu-pinning and mem-policy, vcpus is None."""
        extended = {
            "cpu-quota": {"limit": 3},
            "mem-quota": {"limit": 1},
            "mempage-size": "SIZE_2GB",
            "cpu-pinning-policy": "DEDICATED",
            "mem-policy": "STRICT",
        }
        extra_specs = {"some-key": "some-val"}
        expected_extra_specs = {
            "hw:cpu_policy": "dedicated",
            "hw:numa_mempolicy": "strict",
            "some-key": "some-val",
        }
        self.vimconn._process_extended_config_of_flavor(extended, extra_specs)
        self.assertEqual(mock_process_resource_quota.call_count, 2)
        mock_process_numa_parameters_of_flavor.assert_not_called()
        self.assertEqual(extra_specs, expected_extra_specs)

    @patch.object(
        vimconnector,
        "_process_numa_parameters_of_flavor",
        new_callable=CopyingMock(),
    )
    @patch.object(vimconnector, "process_resource_quota", new_callable=CopyingMock())
    def test_process_extended_config_of_flavor_wrong_cpu_pinning_mem_policy_empty_vcpus(
        self, mock_process_resource_quota, mock_process_numa_parameters_of_flavor
    ):
        """Process extended config, extended has wrong cpu-pinning and mem-policy keys."""
        numas = [
            {"memory": 1},
            {"memory": 2, "vcpu": [2]},
        ]
        extended = {
            "numas": numas,
            "cpu-quota": {"limit": 3},
            "mem-quota": {"limit": 1},
            "mempage-size": "SIZE_2GB",
            "cpu-pinning-pol": "DEDICATED",
            "mem-pol": "STRICT",
        }
        extra_specs = {}
        expected_extra_specs = {}
        self.vimconn._process_extended_config_of_flavor(extended, extra_specs)
        self.assertEqual(mock_process_resource_quota.call_count, 2)
        mock_process_numa_parameters_of_flavor.assert_called_once_with(
            numas, extra_specs
        )
        self.assertEqual(extra_specs, expected_extra_specs)

    @patch.object(
        vimconnector,
        "_process_numa_parameters_of_flavor",
        new_callable=CopyingMock(),
    )
    @patch.object(vimconnector, "process_resource_quota", new_callable=CopyingMock())
    def test_process_extended_config_of_flavor_empty_extended(
        self, mock_process_resource_quota, mock_process_numa_parameters_of_flavor
    ):
        """Process extended config, extended is empty."""
        extended = {}
        extra_specs = {}
        self.vimconn._process_extended_config_of_flavor(extended, extra_specs)
        check_if_assert_not_called(
            [mock_process_resource_quota, mock_process_numa_parameters_of_flavor]
        )
        self.assertEqual(extra_specs, {})

    def test_get_flavor_details_empty_flavor_data(self):
        flavor_data = {}
        expected_result = (64, 1, {}, None)
        result = self.vimconn._get_flavor_details(flavor_data)
        self.assertEqual(result, expected_result)

    def test_get_flavor_details_flavor_data_has_ram_vcpus_extended(self):
        flavor_data = {
            "ram": 32,
            "vcpus": 3,
            "extended": {
                "some-key": "some-val",
            },
        }
        expected_result = (32, 3, {}, {"some-key": "some-val"})
        result = self.vimconn._get_flavor_details(flavor_data)
        self.assertEqual(result, expected_result)

    def test_get_flavor_details_flavor_data_is_none(self):
        flavor_data = None
        with self.assertRaises(AttributeError):
            self.vimconn._get_flavor_details(flavor_data)

    def test_get_flavor_details_flavor_data_has_only_extended(self):
        flavor_data = {
            "extended": {
                "some-key": "some-val",
            }
        }
        expected_result = (64, 1, {}, {"some-key": "some-val"})
        result = self.vimconn._get_flavor_details(flavor_data)
        self.assertEqual(result, expected_result)

    @patch.object(vimconnector, "_get_flavor_details", new_callable=CopyingMock())
    @patch.object(
        vimconnector,
        "_process_extended_config_of_flavor",
        new_callable=CopyingMock(),
    )
    @patch.object(vimconnector, "_change_flavor_name", new_callable=CopyingMock())
    @patch.object(vimconnector, "_reload_connection", new_callable=CopyingMock())
    @patch.object(vimconnector, "_format_exception", new_callable=CopyingMock())
    def test_new_flavor_with_extended_with_extra_specs(
        self,
        mock_format_exception,
        mock_reload_connection,
        mock_change_flavor_name,
        mock_extended_config_of_flavor,
        mock_get_flavor_details,
    ):
        """Create new flavor with using extended parameters and extra specs."""
        name_suffix = 0
        vcpus = 8
        mock_change_flavor_name.return_value = name1
        mock_get_flavor_details.return_value = (
            3,
            vcpus,
            {"some-key": "some-value"},
            extended,
        )
        expected_result = self.new_flavor.id
        result = self.vimconn.new_flavor(flavor_data)
        self.assertEqual(result, expected_result)
        mock_reload_connection.assert_called_once()
        self.new_flavor.set_keys.assert_called_once()
        mock_get_flavor_details.assert_called_once_with(flavor_data)
        mock_change_flavor_name.assert_called_once_with(name1, name_suffix, flavor_data)
        mock_extended_config_of_flavor.assert_called_once_with(
            extended, {"some-key": "some-value"}
        )
        self.vimconn.nova.flavors.create.assert_called_once_with(
            name=name1, ram=3, vcpus=8, disk=50, ephemeral=0, swap=0, is_public=True
        )
        mock_format_exception.assert_not_called()

    @patch.object(vimconnector, "_get_flavor_details", new_callable=CopyingMock())
    @patch.object(
        vimconnector,
        "_process_extended_config_of_flavor",
        new_callable=CopyingMock(),
    )
    @patch.object(vimconnector, "_change_flavor_name", new_callable=CopyingMock())
    @patch.object(vimconnector, "_reload_connection", new_callable=CopyingMock())
    @patch.object(vimconnector, "_format_exception", new_callable=CopyingMock())
    def test_new_flavor_with_extended_without_extra_specs(
        self,
        mock_format_exception,
        mock_reload_connection,
        mock_change_flavor_name,
        mock_extended_config_of_flavor,
        mock_get_flavor_details,
    ):
        """Create new flavor with using extended parameters without extra specs."""
        name_suffix = 0
        vcpus = 8
        mock_change_flavor_name.return_value = name1
        mock_get_flavor_details.return_value = (3, vcpus, {}, extended)
        expected_result = self.new_flavor.id
        result = self.vimconn.new_flavor(flavor_data)
        self.assertEqual(result, expected_result)
        mock_reload_connection.assert_called_once()
        mock_get_flavor_details.assert_called_once_with(flavor_data)
        mock_change_flavor_name.assert_called_once_with(name1, name_suffix, flavor_data)
        mock_extended_config_of_flavor.assert_called_once_with(extended, {})
        self.vimconn.nova.flavors.create.assert_called_once_with(
            name=name1, ram=3, vcpus=vcpus, disk=50, ephemeral=0, swap=0, is_public=True
        )
        check_if_assert_not_called([self.new_flavor.set_keys, mock_format_exception])

    @patch.object(vimconnector, "_get_flavor_details", new_callable=CopyingMock())
    @patch.object(
        vimconnector,
        "_process_extended_config_of_flavor",
        new_callable=CopyingMock(),
    )
    @patch.object(vimconnector, "_change_flavor_name", new_callable=CopyingMock())
    @patch.object(vimconnector, "_reload_connection", new_callable=CopyingMock())
    @patch.object(vimconnector, "_format_exception", new_callable=CopyingMock())
    def test_new_flavor_change_name_if_used_false_with_extended(
        self,
        mock_format_exception,
        mock_reload_connection,
        mock_change_flavor_name,
        mock_extended_config_of_flavor,
        mock_get_flavor_details,
    ):
        """Create new flavor, change_name_if_used_false, there is extended."""
        vcpus = 8
        mock_get_flavor_details.return_value = (3, vcpus, {}, extended)
        expected_result = self.new_flavor.id
        result = self.vimconn.new_flavor(flavor_data, False)
        self.assertEqual(result, expected_result)
        mock_reload_connection.assert_called_once()
        self.assertEqual(mock_get_flavor_details.call_count, 1)
        mock_extended_config_of_flavor.assert_called_once_with(extended, {})
        self.vimconn.nova.flavors.create.assert_called_once_with(
            name=name1, ram=3, vcpus=8, disk=50, ephemeral=0, swap=0, is_public=True
        )
        check_if_assert_not_called(
            [mock_change_flavor_name, mock_format_exception, self.new_flavor.set_keys]
        )

    @patch.object(vimconnector, "_get_flavor_details", new_callable=CopyingMock())
    @patch.object(
        vimconnector,
        "_process_extended_config_of_flavor",
        new_callable=CopyingMock(),
    )
    @patch.object(vimconnector, "_change_flavor_name", new_callable=CopyingMock())
    @patch.object(vimconnector, "_reload_connection", new_callable=CopyingMock())
    @patch.object(vimconnector, "_format_exception", new_callable=CopyingMock())
    def test_new_flavor_change_name_if_used_true_without_extended(
        self,
        mock_format_exception,
        mock_reload_connection,
        mock_change_flavor_name,
        mock_extended_config_of_flavor,
        mock_get_flavor_details,
    ):
        """Create new flavor without extended parameters."""
        name_suffix = 0
        mock_change_flavor_name.return_value = name1
        expected_result = self.new_flavor.id
        mock_get_flavor_details.return_value = (3, 8, {}, None)
        result = self.vimconn.new_flavor(flavor_data2)
        self.assertEqual(result, expected_result)
        mock_reload_connection.assert_called_once()
        mock_change_flavor_name.assert_called_once_with(
            name1, name_suffix, flavor_data2
        )
        self.assertEqual(mock_get_flavor_details.call_count, 1)
        self.vimconn.nova.flavors.create.assert_called_once_with(
            name=name1, ram=3, vcpus=8, disk=50, ephemeral=0, swap=0, is_public=True
        )
        check_if_assert_not_called(
            [
                self.new_flavor.set_keys,
                mock_extended_config_of_flavor,
                mock_format_exception,
            ]
        )

    @patch.object(vimconnector, "_get_flavor_details", new_callable=CopyingMock())
    @patch.object(
        vimconnector,
        "_process_extended_config_of_flavor",
        new_callable=CopyingMock(),
    )
    @patch.object(vimconnector, "_change_flavor_name", new_callable=CopyingMock())
    @patch.object(vimconnector, "_reload_connection", new_callable=CopyingMock())
    @patch.object(vimconnector, "_format_exception", new_callable=CopyingMock())
    def test_new_flavor_reload_connection_exception(
        self,
        mock_format_exception,
        mock_reload_connection,
        mock_change_flavor_name,
        mock_extended_config_of_flavor,
        mock_get_flavor_details,
    ):
        """Create new flavor, reload connection exception occurred."""
        error_msg = "Can not connect to client APIs."
        error = nvExceptions.ClientException(error_msg)
        mock_change_flavor_name.return_value = name1
        mock_reload_connection.side_effect = error
        with self.assertRaises(Exception) as err:
            self.vimconn.new_flavor(flavor_data2)
            self.assertEqual(str(err.exception), "Can not connect to client APIs.")
        self.assertEqual(mock_reload_connection.call_count, 1)
        call_mock_format_exception = mock_format_exception.call_args
        self.assertEqual(
            str(call_mock_format_exception[0][0]), str(ClientException(error_msg))
        )
        check_if_assert_not_called(
            [
                mock_change_flavor_name,
                mock_get_flavor_details,
                mock_extended_config_of_flavor,
                self.vimconn.nova.flavors.create,
            ]
        )

    @patch.object(vimconnector, "_get_flavor_details", new_callable=CopyingMock())
    @patch.object(
        vimconnector,
        "_process_extended_config_of_flavor",
        new_callable=CopyingMock(autospec=True),
    )
    @patch.object(vimconnector, "_change_flavor_name", new_callable=CopyingMock())
    @patch.object(vimconnector, "_reload_connection", new_callable=CopyingMock())
    @patch.object(vimconnector, "_format_exception", new_callable=CopyingMock())
    def test_new_flavor_flavor_data_without_name(
        self,
        mock_format_exception,
        mock_reload_connection,
        mock_change_flavor_name,
        mock_extended_config_of_flavor,
        mock_get_flavor_details,
    ):
        """Create new flavor, flavor data does not have name."""
        flavor_data3 = {
            "ram": 3,
            "vcpus": 8,
            "disk": 50,
        }
        error_msg = "name"
        self.vimconn.new_flavor(flavor_data3)
        mock_format_exception.assert_called_once()
        call_mock_format_exception = mock_format_exception.call_args
        self.assertEqual(
            str(call_mock_format_exception[0][0]), str(KeyError(error_msg))
        )
        check_if_assert_not_called(
            [
                mock_reload_connection,
                mock_change_flavor_name,
                mock_get_flavor_details,
                mock_extended_config_of_flavor,
                self.vimconn.nova.flavors.create,
            ]
        )

    @patch.object(vimconnector, "_get_flavor_details", new_callable=CopyingMock())
    @patch.object(
        vimconnector,
        "_process_extended_config_of_flavor",
        new_callable=CopyingMock(),
    )
    @patch.object(vimconnector, "_change_flavor_name", new_callable=CopyingMock())
    @patch.object(vimconnector, "_reload_connection", new_callable=CopyingMock())
    @patch.object(vimconnector, "_format_exception", new_callable=CopyingMock())
    def test_new_flavor_change_flavor_name_has_extended_conflict_exception_recovered_in_retry(
        self,
        mock_format_exception,
        mock_reload_connection,
        mock_change_flavor_name,
        mock_extended_config_of_flavor,
        mock_get_flavor_details,
    ):
        """Create new flavor, nvExceptions.Conflict occurred and recovered, there is extended config."""
        name_suffix = 0
        error_msg = "Conflict has occurred while creating flavor name."
        error2 = nvExceptions.Conflict(error_msg)
        mock_change_flavor_name.side_effect = [error2, "sample-flavor-3"]
        expected_result = self.new_flavor.id
        mock_get_flavor_details.return_value = (3, 8, {}, extended)
        result = self.vimconn.new_flavor(flavor_data2)
        self.assertEqual(result, expected_result)
        self.assertEqual(mock_reload_connection.call_count, 2)
        mock_change_flavor_name.assert_called_with(name1, name_suffix, flavor_data2)
        self.assertEqual(mock_change_flavor_name.call_count, 2)
        self.assertEqual(mock_get_flavor_details.call_count, 1)
        self.assertEqual(mock_extended_config_of_flavor.call_count, 1)
        self.vimconn.nova.flavors.create.assert_called_once_with(
            name="sample-flavor-3",
            ram=3,
            vcpus=8,
            disk=50,
            ephemeral=0,
            swap=0,
            is_public=True,
        )
        check_if_assert_not_called([self.new_flavor.set_keys, mock_format_exception])

    @patch.object(vimconnector, "_get_flavor_details", new_callable=CopyingMock())
    @patch.object(
        vimconnector,
        "_process_extended_config_of_flavor",
        new_callable=CopyingMock(),
    )
    @patch.object(vimconnector, "_change_flavor_name", new_callable=CopyingMock())
    @patch.object(vimconnector, "_reload_connection", new_callable=CopyingMock())
    @patch.object(vimconnector, "_format_exception", new_callable=CopyingMock())
    def test_new_flavor_change_flavor_name_without_extended_conflict_exception_recovered_in_retry(
        self,
        mock_format_exception,
        mock_reload_connection,
        mock_change_flavor_name,
        mock_extended_config_of_flavor,
        mock_get_flavor_details,
    ):
        """Create new flavor, nvExceptions.Conflict occurred and recovered, there is not extended config."""
        name_suffix = 0
        error2 = nvExceptions.Conflict(
            "Conflict has occurred while creating flavor name."
        )
        mock_change_flavor_name.side_effect = [error2, "sample-flavor-3"]
        expected_result = self.new_flavor.id
        mock_get_flavor_details.return_value = (3, 8, {}, None)
        result = self.vimconn.new_flavor(flavor_data2)
        self.assertEqual(result, expected_result)
        self.assertEqual(mock_reload_connection.call_count, 2)
        mock_change_flavor_name.assert_called_with(name1, name_suffix, flavor_data2)
        self.assertEqual(mock_change_flavor_name.call_count, 2)
        self.assertEqual(mock_get_flavor_details.call_count, 1)
        self.vimconn.nova.flavors.create.assert_called_once_with(
            name="sample-flavor-3",
            ram=3,
            vcpus=8,
            disk=50,
            ephemeral=0,
            swap=0,
            is_public=True,
        )
        check_if_assert_not_called(
            [
                self.new_flavor.set_keys,
                mock_extended_config_of_flavor,
                mock_format_exception,
            ]
        )

    @patch.object(vimconnector, "_get_flavor_details", new_callable=CopyingMock())
    @patch.object(
        vimconnector,
        "_process_extended_config_of_flavor",
        new_callable=CopyingMock(),
    )
    @patch.object(vimconnector, "_change_flavor_name", new_callable=CopyingMock())
    @patch.object(vimconnector, "_reload_connection", new_callable=CopyingMock())
    @patch.object(vimconnector, "_format_exception", new_callable=CopyingMock())
    def test_new_flavor_change_flavor_name_conflict_exception_change_name_if_used_false(
        self,
        mock_format_exception,
        mock_reload_connection,
        mock_change_flavor_name,
        mock_extended_config_of_flavor,
        mock_get_flavor_details,
    ):
        """Create new flavor, nvExceptions.Conflict occurred,
        change_name_if_used is false."""
        change_name_if_used = False
        error_msg = "Conflict has occurred while creating flavor name."
        error2 = nvExceptions.Conflict(error_msg)
        mock_get_flavor_details.return_value = (4, 8, {}, None)
        self.vimconn.nova.flavors.create.side_effect = error2
        with self.assertRaises(Exception) as err:
            self.vimconn.new_flavor(flavor_data2, change_name_if_used)
            self.assertEqual(str(err.exception), error_msg)
            self.assertEqual(type(err.exception), nvExceptions.Conflict)
        self.vimconn.nova.flavors.create.assert_called_with(
            name="sample-flavor",
            ram=4,
            vcpus=8,
            disk=50,
            ephemeral=0,
            swap=0,
            is_public=True,
        )
        self.assertEqual(mock_get_flavor_details.call_count, 3)
        self.assertEqual(self.vimconn.nova.flavors.create.call_count, 3)
        self.assertEqual(mock_reload_connection.call_count, 3)
        check_if_assert_not_called(
            [mock_change_flavor_name, mock_extended_config_of_flavor]
        )
        _call_mock_format_exception = mock_format_exception.call_args
        self.assertEqual(
            str(_call_mock_format_exception[0][0]), str(Conflict(error_msg))
        )
        self.assertEqual(mock_format_exception.call_count, 3)

    @patch.object(vimconnector, "_get_flavor_details", new_callable=CopyingMock())
    @patch.object(
        vimconnector,
        "_process_extended_config_of_flavor",
        new_callable=CopyingMock(),
    )
    @patch.object(vimconnector, "_change_flavor_name", new_callable=CopyingMock())
    @patch.object(vimconnector, "_reload_connection", new_callable=CopyingMock())
    @patch.object(vimconnector, "_format_exception", new_callable=CopyingMock())
    def test_new_flavor_client_exception_occurred_change_name_if_used_true(
        self,
        mock_format_exception,
        mock_reload_connection,
        mock_change_flavor_name,
        mock_extended_config_of_flavor,
        mock_get_flavor_details,
    ):
        """Create new flavor, nvExceptions.ClientException occurred,
        change_name_if_used is true."""
        error_msg = "Connection failed."
        error2 = nvExceptions.ClientException(error_msg)
        mock_change_flavor_name.side_effect = [
            "sample-flavor-3",
            "sample-flavor-4",
            "sample-flavor-5",
        ]
        mock_get_flavor_details.return_value = (3, 8, {}, None)
        self.vimconn.nova.flavors.create.side_effect = error2
        with self.assertRaises(Exception) as err:
            self.vimconn.new_flavor(flavor_data2)
            self.assertEqual(
                str(err.exception), "Conflict has occurred while creating flavor name."
            )
            self.assertEqual(type(err.exception), nvExceptions.Conflict)
        self.assertEqual(self.vimconn.nova.flavors.create.call_count, 1)
        _call_mock_nova_create_flavor = self.vimconn.nova.flavors.create.call_args_list
        self.assertEqual(
            _call_mock_nova_create_flavor[0][1],
            (
                {
                    "name": "sample-flavor-3",
                    "ram": 3,
                    "vcpus": 8,
                    "disk": 50,
                    "ephemeral": 0,
                    "swap": 0,
                    "is_public": True,
                }
            ),
        )

        self.assertEqual(mock_reload_connection.call_count, 1)
        self.assertEqual(mock_get_flavor_details.call_count, 1)
        _call_mock_change_flavor = mock_change_flavor_name.call_args_list
        self.assertEqual(
            _call_mock_change_flavor[0][0],
            (
                "sample-flavor",
                0,
                {"name": "sample-flavor", "ram": 3, "vcpus": 8, "disk": 50},
            ),
        )
        self.assertEqual(mock_change_flavor_name.call_count, 1)
        mock_extended_config_of_flavor.assert_not_called()
        call_mock_format_exception = mock_format_exception.call_args
        self.assertEqual(
            str(call_mock_format_exception[0][0]), str(ClientException(error_msg))
        )
        self.assertEqual(mock_format_exception.call_count, 1)

    @patch.object(vimconnector, "_get_flavor_details", new_callable=CopyingMock())
    @patch.object(
        vimconnector,
        "_process_extended_config_of_flavor",
        new_callable=CopyingMock(),
    )
    @patch.object(vimconnector, "_change_flavor_name", new_callable=CopyingMock())
    @patch.object(vimconnector, "_reload_connection", new_callable=CopyingMock())
    @patch.object(vimconnector, "_format_exception", new_callable=CopyingMock())
    def test_new_flavor_change_flavor_name_conflict_exception_occurred_change_name_if_used_true(
        self,
        mock_format_exception,
        mock_reload_connection,
        mock_change_flavor_name,
        mock_extended_config_of_flavor,
        mock_get_flavor_details,
    ):
        """Create new flavor, nvExceptions.Conflict occurred,
        change_name_if_used is true."""
        error_msg = "Conflict has occurred while creating flavor name."
        error2 = nvExceptions.Conflict(error_msg)
        mock_change_flavor_name.side_effect = [
            "sample-flavor-3",
            "sample-flavor-4",
            "sample-flavor-5",
        ]
        mock_get_flavor_details.return_value = (3, 8, {}, None)
        self.vimconn.nova.flavors.create.side_effect = error2
        with self.assertRaises(Exception) as err:
            self.vimconn.new_flavor(flavor_data2)
            self.assertEqual(str(err.exception), error_msg)
            self.assertEqual(type(err.exception), nvExceptions.Conflict)
        self.assertEqual(self.vimconn.nova.flavors.create.call_count, 3)
        _call_mock_nova_create_flavor = self.vimconn.nova.flavors.create.call_args_list
        self.assertEqual(
            _call_mock_nova_create_flavor[0][1],
            (
                {
                    "name": "sample-flavor-3",
                    "ram": 3,
                    "vcpus": 8,
                    "disk": 50,
                    "ephemeral": 0,
                    "swap": 0,
                    "is_public": True,
                }
            ),
        )
        self.assertEqual(
            _call_mock_nova_create_flavor[1][1],
            (
                {
                    "name": "sample-flavor-4",
                    "ram": 3,
                    "vcpus": 8,
                    "disk": 50,
                    "ephemeral": 0,
                    "swap": 0,
                    "is_public": True,
                }
            ),
        )
        self.assertEqual(
            _call_mock_nova_create_flavor[2][1],
            (
                {
                    "name": "sample-flavor-5",
                    "ram": 3,
                    "vcpus": 8,
                    "disk": 50,
                    "ephemeral": 0,
                    "swap": 0,
                    "is_public": True,
                }
            ),
        )
        self.assertEqual(mock_reload_connection.call_count, 3)
        _call_mock_change_flavor = mock_change_flavor_name.call_args_list
        self.assertEqual(
            _call_mock_change_flavor[0][0],
            (
                "sample-flavor",
                0,
                {"name": "sample-flavor", "ram": 3, "vcpus": 8, "disk": 50},
            ),
        )
        self.assertEqual(
            _call_mock_change_flavor[1][0],
            (
                "sample-flavor-3",
                0,
                {"name": "sample-flavor", "ram": 3, "vcpus": 8, "disk": 50},
            ),
        )
        self.assertEqual(
            _call_mock_change_flavor[2][0],
            (
                "sample-flavor-4",
                0,
                {"name": "sample-flavor", "ram": 3, "vcpus": 8, "disk": 50},
            ),
        )
        self.assertEqual(mock_change_flavor_name.call_count, 3)
        mock_extended_config_of_flavor.assert_not_called()
        call_mock_format_exception = mock_format_exception.call_args
        self.assertEqual(
            str(call_mock_format_exception[0][0]), str(Conflict(error_msg))
        )
        self.assertEqual(mock_format_exception.call_count, 1)

    def test_process_process_vio_numa_nodes_without_numa_with_extra_spec(self):
        numa_nodes = 0
        extra_specs = {"hw:numa_nodes": "0"}
        expected_extra_spec = {
            "vmware:latency_sensitivity_level": "high",
            "hw:numa_nodes": "0",
        }
        self.vimconn.process_vio_numa_nodes(numa_nodes, extra_specs)
        self.assertDictEqual(extra_specs, expected_extra_spec)

    def test_process_process_vio_numa_nodes_list_type_numa_nodes_empty_extra_spec(self):
        numa_nodes = [7, 9, 4]
        extra_specs = {}
        expected_extra_spec = {
            "vmware:latency_sensitivity_level": "high",
        }
        self.vimconn.process_vio_numa_nodes(numa_nodes, extra_specs)
        self.assertDictEqual(extra_specs, expected_extra_spec)

    def test_process_process_vio_numa_nodes_with_numa_with_extra_spec(self):
        numa_nodes = 5
        extra_specs = {"hw:numa_nodes": "5"}
        expected_extra_spec = {
            "vmware:latency_sensitivity_level": "high",
            "hw:numa_nodes": "5",
        }
        self.vimconn.process_vio_numa_nodes(numa_nodes, extra_specs)
        self.assertDictEqual(extra_specs, expected_extra_spec)

    def test_process_process_vio_numa_nodes_none_numa_nodes(self):
        numa_nodes = None
        extra_specs = {"hw:numa_nodes": "None"}
        expected_extra_spec = {
            "vmware:latency_sensitivity_level": "high",
            "hw:numa_nodes": "None",
        }
        self.vimconn.process_vio_numa_nodes(numa_nodes, extra_specs)
        self.assertDictEqual(extra_specs, expected_extra_spec)

    def test_process_process_vio_numa_nodes_invalid_type_extra_specs(self):
        numa_nodes = 5
        extra_specs = []
        with self.assertRaises(TypeError):
            self.vimconn.process_vio_numa_nodes(numa_nodes, extra_specs)


if __name__ == "__main__":
    unittest.main()
