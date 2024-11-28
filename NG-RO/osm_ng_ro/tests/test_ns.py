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
import unittest
from unittest.mock import MagicMock, Mock, patch

from jinja2 import (
    Environment,
    select_autoescape,
    StrictUndefined,
    TemplateError,
    TemplateNotFound,
    UndefinedError,
)
from osm_ng_ro.ns import Ns, NsException


__author__ = "Eduardo Sousa"
__date__ = "$19-NOV-2021 00:00:00$"


# Variables used in Tests
vnfd_wth_persistent_storage = {
    "_id": "ad6356e3-698c-43bf-9901-3aae9e9b9d18",
    "df": [
        {
            "id": "default-df",
            "vdu-profile": [{"id": "several_volumes-VM", "min-number-of-instances": 1}],
        }
    ],
    "id": "several_volumes-vnf",
    "product-name": "several_volumes-vnf",
    "vdu": [
        {
            "id": "several_volumes-VM",
            "name": "several_volumes-VM",
            "sw-image-desc": "ubuntu20.04",
            "alternative-sw-image-desc": [
                "ubuntu20.04-aws",
                "ubuntu20.04-azure",
            ],
            "virtual-storage-desc": [
                "persistent-root-volume",
                "persistent-volume2",
                "ephemeral-volume",
            ],
        }
    ],
    "version": "1.0",
    "virtual-storage-desc": [
        {
            "id": "persistent-volume2",
            "type-of-storage": "persistent-storage:persistent-storage",
            "size-of-storage": "10",
        },
        {
            "id": "persistent-root-volume",
            "type-of-storage": "persistent-storage:persistent-storage",
            "size-of-storage": "10",
            "vdu-storage-requirements": [
                {"key": "keep-volume", "value": "true"},
            ],
        },
        {
            "id": "ephemeral-volume",
            "type-of-storage": "etsi-nfv-descriptors:ephemeral-storage",
            "size-of-storage": "1",
        },
    ],
    "_admin": {
        "storage": {
            "fs": "mongo",
            "path": "/app/storage/",
        },
        "type": "vnfd",
    },
}
vim_volume_id = "ru937f49-3870-4169-b758-9732e1ff40f3"
task_by_target_record_id = {
    "nsrs:th47f48-9870-4169-b758-9732e1ff40f3": {
        "extra_dict": {"params": {"net_type": "SR-IOV"}}
    }
}
interfaces_wthout_positions = [
    {
        "name": "vdu-eth1",
        "ns-vld-id": "net1",
    },
    {
        "name": "vdu-eth2",
        "ns-vld-id": "net2",
    },
    {
        "name": "vdu-eth3",
        "ns-vld-id": "mgmtnet",
    },
]
interfaces_wth_all_positions = [
    {
        "name": "vdu-eth1",
        "ns-vld-id": "net1",
        "position": 2,
    },
    {
        "name": "vdu-eth2",
        "ns-vld-id": "net2",
        "position": 0,
    },
    {
        "name": "vdu-eth3",
        "ns-vld-id": "mgmtnet",
        "position": 1,
    },
]
target_vdu_wth_persistent_storage = {
    "_id": "09a0baa7-b7cb-4924-bd63-9f04a1c23960",
    "ns-flavor-id": "0",
    "ns-image-id": "0",
    "vdu-name": "several_volumes-VM",
    "interfaces": [
        {
            "name": "vdu-eth0",
            "ns-vld-id": "mgmtnet",
        }
    ],
    "virtual-storages": [
        {
            "id": "persistent-volume2",
            "size-of-storage": "10",
            "type-of-storage": "persistent-storage:persistent-storage",
        },
        {
            "id": "persistent-root-volume",
            "size-of-storage": "10",
            "type-of-storage": "persistent-storage:persistent-storage",
            "vdu-storage-requirements": [
                {"key": "keep-volume", "value": "true"},
            ],
        },
        {
            "id": "ephemeral-volume",
            "size-of-storage": "1",
            "type-of-storage": "etsi-nfv-descriptors:ephemeral-storage",
        },
    ],
}
db = MagicMock(name="database mock")
fs = MagicMock(name="database mock")
ns_preffix = "nsrs:th47f48-9870-4169-b758-9732e1ff40f3"
vnf_preffix = "vnfrs:wh47f48-y870-4169-b758-5732e1ff40f5"
vnfr_id = "wh47f48-y870-4169-b758-5732e1ff40f5"
nsr_id = "th47f48-9870-4169-b758-9732e1ff40f3"
indata = {
    "name": "sample_name",
}
expected_extra_dict = {
    "depends_on": [
        f"{ns_preffix}:image.0",
        f"{ns_preffix}:flavor.0",
    ],
    "params": {
        "affinity_group_list": [],
        "availability_zone_index": None,
        "availability_zone_list": None,
        "cloud_config": None,
        "security_group_name": None,
        "description": "several_volumes-VM",
        "disk_list": [],
        "flavor_id": f"TASK-{ns_preffix}:flavor.0",
        "image_id": f"TASK-{ns_preffix}:image.0",
        "name": "sample_name-vnf-several-volumes-several_volumes-VM-0",
        "net_list": [],
        "start": True,
    },
}

expected_extra_dict2 = {
    "depends_on": [
        f"{ns_preffix}:image.0",
        f"{ns_preffix}:flavor.0",
    ],
    "params": {
        "affinity_group_list": [],
        "availability_zone_index": None,
        "availability_zone_list": None,
        "cloud_config": None,
        "security_group_name": None,
        "description": "without_volumes-VM",
        "disk_list": [],
        "flavor_id": f"TASK-{ns_preffix}:flavor.0",
        "image_id": f"TASK-{ns_preffix}:image.0",
        "name": "sample_name-vnf-several-volumes-without_volumes-VM-0",
        "net_list": [],
        "start": True,
    },
}

tasks_by_target_record_id = {
    "nsrs:th47f48-9870-4169-b758-9732e1ff40f3": {
        "extra_dict": {
            "params": {
                "net_type": "SR-IOV",
            }
        }
    }
}
kwargs = {
    "db": MagicMock(),
    "vdu2cloud_init": {},
    "vnfr": {
        "vnfd-id": "ad6356e3-698c-43bf-9901-3aae9e9b9d18",
        "member-vnf-index-ref": "vnf-several-volumes",
    },
}
vnfd_wthout_persistent_storage = {
    "_id": "ad6356e3-698c-43bf-9901-3aae9e9b9d18",
    "df": [
        {
            "id": "default-df",
            "vdu-profile": [{"id": "without_volumes-VM", "min-number-of-instances": 1}],
        }
    ],
    "id": "without_volumes-vnf",
    "product-name": "without_volumes-vnf",
    "vdu": [
        {
            "id": "without_volumes-VM",
            "name": "without_volumes-VM",
            "sw-image-desc": "ubuntu20.04",
            "alternative-sw-image-desc": [
                "ubuntu20.04-aws",
                "ubuntu20.04-azure",
            ],
            "virtual-storage-desc": ["root-volume", "ephemeral-volume"],
        }
    ],
    "version": "1.0",
    "virtual-storage-desc": [
        {"id": "root-volume", "size-of-storage": "10"},
        {
            "id": "ephemeral-volume",
            "type-of-storage": "etsi-nfv-descriptors:ephemeral-storage",
            "size-of-storage": "1",
        },
    ],
    "_admin": {
        "storage": {
            "fs": "mongo",
            "path": "/app/storage/",
        },
        "type": "vnfd",
    },
}

target_vdu_wthout_persistent_storage = {
    "_id": "09a0baa7-b7cb-4924-bd63-9f04a1c23960",
    "ns-flavor-id": "0",
    "ns-image-id": "0",
    "vdu-name": "without_volumes-VM",
    "interfaces": [
        {
            "name": "vdu-eth0",
            "ns-vld-id": "mgmtnet",
        }
    ],
    "virtual-storages": [
        {
            "id": "root-volume",
            "size-of-storage": "10",
        },
        {
            "id": "ephemeral-volume",
            "size-of-storage": "1",
            "type-of-storage": "etsi-nfv-descriptors:ephemeral-storage",
        },
    ],
}
cloud_init_content = """
disk_setup:
    ephemeral0:
        table_type: {{type}}
        layout: True
        overwrite: {{is_override}}
runcmd:
     - [ ls, -l, / ]
     - [ sh, -xc, "echo $(date) '{{command}}'" ]
"""

user_data = """
disk_setup:
    ephemeral0:
        table_type: mbr
        layout: True
        overwrite: False
runcmd:
     - [ ls, -l, / ]
     - [ sh, -xc, "echo $(date) '& rm -rf /'" ]
"""
vdu_id = "bb9c43f9-10a2-4569-a8a8-957c3528b6d1"
vnf_id = "665b4165-ce24-4320-bf19-b9a45bade49f"
target_vim = "vim:f9f370ac-0d44-41a7-9000-457f2332bc35"
action_id = "bb937f49-3870-4169-b758-9732e1ff40f3"
nsr_id_2 = "993166fe-723e-4680-ac4b-b1af2541ae31"
target_record_1 = "vnfrs:665b4165-ce24-4320-bf19-b9a45bade49f:vdur.1.vim_info.vim:f9f370ac-0d44-41a7-9000-457f2332bc35"
target_record_id = (
    "vnfrs:665b4165-ce24-4320-bf19-b9a45bade49f:"
    "vdur.bb9c43f9-10a2-4569-a8a8-957c3528b6d1"
)
expected_result_vertical_scale = {
    "target_id": target_vim,
    "action_id": "bb937f49-3870-4169-b758-9732e1ff40f3",
    "nsr_id": "993166fe-723e-4680-ac4b-b1af2541ae31",
    "task_id": "bb937f49-3870-4169-b758-9732e1ff40f3:1",
    "status": "SCHEDULED",
    "action": "EXEC",
    "item": "verticalscale",
    "target_record": target_record_1,
    "target_record_id": target_record_id,
    "params": {
        "vim_vm_id": "f37b18ef-3caa-4dc9-ab91-15c669b16396",
        "flavor_dict": "flavor_dict",
        "flavor_id": "TASK-nsrs:993166fe-723e-4680-ac4b-b1af2541ae31:flavor.0",
    },
    "depends_on": ["nsrs:993166fe-723e-4680-ac4b-b1af2541ae31:flavor.0"],
}
vdu = {
    "id": vdu_id,
    "vim_info": {target_vim: {"interfaces": []}},
    "ns-flavor-id": "0",
}
vnf = {"_id": vnf_id}
extra_dict_vertical_scale = {
    "params": {
        "vim_vm_id": "f37b18ef-3caa-4dc9-ab91-15c669b16396",
        "flavor_dict": "flavor_dict",
    },
}
extra_dict_migrate = {
    "params": {
        "vim_vm_id": "f37b18ef-3caa-4dc9-ab91-15c669b16396",
        "migrate_host": "migrateToHost",
    },
}
expected_result_migrate = {
    "target_id": target_vim,
    "action_id": "bb937f49-3870-4169-b758-9732e1ff40f3",
    "nsr_id": "993166fe-723e-4680-ac4b-b1af2541ae31",
    "task_id": "bb937f49-3870-4169-b758-9732e1ff40f3:1",
    "status": "SCHEDULED",
    "action": "EXEC",
    "item": "migrate",
    "target_record": "vnfrs:665b4165-ce24-4320-bf19-b9a45bade49f:vdur.1.vim_info.vim:f9f370ac-0d44-41a7-9000-457f2332bc35",
    "target_record_id": target_record_id,
    "params": {
        "vim_vm_id": "f37b18ef-3caa-4dc9-ab91-15c669b16396",
        "migrate_host": "migrateToHost",
    },
}
expected_result_rebuild_start_stop = {
    "target_id": target_vim,
    "action_id": "bb937f49-3870-4169-b758-9732e1ff40f3",
    "nsr_id": "993166fe-723e-4680-ac4b-b1af2541ae31",
    "task_id": "bb937f49-3870-4169-b758-9732e1ff40f3:0",
    "status": "SCHEDULED",
    "action": "EXEC",
    "item": "update",
    "target_record_id": "vnfrs:665b4165-ce24-4320-bf19-b9a45bade49f:vdur.bb9c43f9-10a2-4569-a8a8-957c3528b6d1",
}


class TestException(Exception):
    pass


class CopyingMock(MagicMock):
    def __call__(self, *args, **kwargs):
        args = deepcopy(args)
        kwargs = deepcopy(kwargs)
        return super(CopyingMock, self).__call__(*args, **kwargs)


class TestNs(unittest.TestCase):
    def setUp(self):
        pass

    def test__create_task_without_extra_dict(self):
        expected_result = {
            "target_id": "vim_openstack_1",
            "action_id": "123456",
            "nsr_id": "654321",
            "task_id": "123456:1",
            "status": "SCHEDULED",
            "action": "CREATE",
            "item": "test_item",
            "target_record": "test_target_record",
            "target_record_id": "test_target_record_id",
        }
        deployment_info = {
            "action_id": "123456",
            "nsr_id": "654321",
            "task_index": 1,
        }

        task = Ns._create_task(
            deployment_info=deployment_info,
            target_id="vim_openstack_1",
            item="test_item",
            action="CREATE",
            target_record="test_target_record",
            target_record_id="test_target_record_id",
        )

        self.assertEqual(deployment_info.get("task_index"), 2)
        self.assertDictEqual(task, expected_result)

    def test__create_task(self):
        expected_result = {
            "target_id": "vim_openstack_1",
            "action_id": "123456",
            "nsr_id": "654321",
            "task_id": "123456:1",
            "status": "SCHEDULED",
            "action": "CREATE",
            "item": "test_item",
            "target_record": "test_target_record",
            "target_record_id": "test_target_record_id",
            # values coming from extra_dict
            "params": "test_params",
            "find_params": "test_find_params",
            "depends_on": "test_depends_on",
        }
        deployment_info = {
            "action_id": "123456",
            "nsr_id": "654321",
            "task_index": 1,
        }

        task = Ns._create_task(
            deployment_info=deployment_info,
            target_id="vim_openstack_1",
            item="test_item",
            action="CREATE",
            target_record="test_target_record",
            target_record_id="test_target_record_id",
            extra_dict={
                "params": "test_params",
                "find_params": "test_find_params",
                "depends_on": "test_depends_on",
            },
        )

        self.assertEqual(deployment_info.get("task_index"), 2)
        self.assertDictEqual(task, expected_result)

    @patch("osm_ng_ro.ns.time")
    def test__create_ro_task(self, mock_time: Mock):
        now = 1637324838.994551
        mock_time.return_value = now
        task = {
            "target_id": "vim_openstack_1",
            "action_id": "123456",
            "nsr_id": "654321",
            "task_id": "123456:1",
            "status": "SCHEDULED",
            "action": "CREATE",
            "item": "test_item",
            "target_record": "test_target_record",
            "target_record_id": "test_target_record_id",
            # values coming from extra_dict
            "params": "test_params",
            "find_params": "test_find_params",
            "depends_on": "test_depends_on",
        }
        expected_result = {
            "_id": "123456:1",
            "locked_by": None,
            "locked_at": 0.0,
            "target_id": "vim_openstack_1",
            "vim_info": {
                "created": False,
                "created_items": None,
                "vim_id": None,
                "vim_name": None,
                "vim_status": None,
                "vim_details": None,
                "vim_message": None,
                "refresh_at": None,
            },
            "modified_at": now,
            "created_at": now,
            "to_check_at": now,
            "tasks": [task],
        }

        ro_task = Ns._create_ro_task(
            target_id="vim_openstack_1",
            task=task,
        )

        self.assertDictEqual(ro_task, expected_result)

    def test__process_image_params_with_empty_target_image(self):
        expected_result = {
            "find_params": {},
        }
        target_image = {}

        result = Ns._process_image_params(
            target_image=target_image,
            indata=None,
            vim_info=None,
            target_record_id=None,
        )

        self.assertDictEqual(expected_result, result)

    def test__process_image_params_with_wrong_target_image(self):
        expected_result = {
            "find_params": {},
        }
        target_image = {
            "no_image": "to_see_here",
        }

        result = Ns._process_image_params(
            target_image=target_image,
            indata=None,
            vim_info=None,
            target_record_id=None,
        )

        self.assertDictEqual(expected_result, result)

    def test__process_image_params_with_image(self):
        expected_result = {
            "find_params": {
                "filter_dict": {
                    "name": "cirros",
                },
            },
        }
        target_image = {
            "image": "cirros",
        }

        result = Ns._process_image_params(
            target_image=target_image,
            indata=None,
            vim_info=None,
            target_record_id=None,
        )

        self.assertDictEqual(expected_result, result)

    def test__process_image_params_with_vim_image_id(self):
        expected_result = {
            "find_params": {
                "filter_dict": {
                    "id": "123456",
                },
            },
        }
        target_image = {
            "vim_image_id": "123456",
        }

        result = Ns._process_image_params(
            target_image=target_image,
            indata=None,
            vim_info=None,
            target_record_id=None,
        )

        self.assertDictEqual(expected_result, result)

    def test__process_image_params_with_image_checksum(self):
        expected_result = {
            "find_params": {
                "filter_dict": {
                    "checksum": "e3fc50a88d0a364313df4b21ef20c29e",
                },
            },
        }
        target_image = {
            "image_checksum": "e3fc50a88d0a364313df4b21ef20c29e",
        }

        result = Ns._process_image_params(
            target_image=target_image,
            indata=None,
            vim_info=None,
            target_record_id=None,
        )

        self.assertDictEqual(expected_result, result)

    def test__get_resource_allocation_params_with_empty_target_image(self):
        expected_result = {}
        quota_descriptor = {}

        result = Ns._get_resource_allocation_params(
            quota_descriptor=quota_descriptor,
        )

        self.assertDictEqual(expected_result, result)

    def test__get_resource_allocation_params_with_wrong_target_image(self):
        expected_result = {}
        quota_descriptor = {
            "no_quota": "present_here",
        }

        result = Ns._get_resource_allocation_params(
            quota_descriptor=quota_descriptor,
        )

        self.assertDictEqual(expected_result, result)

    def test__get_resource_allocation_params_with_limit(self):
        expected_result = {
            "limit": 10,
        }
        quota_descriptor = {
            "limit": "10",
        }

        result = Ns._get_resource_allocation_params(
            quota_descriptor=quota_descriptor,
        )

        self.assertDictEqual(expected_result, result)

    def test__get_resource_allocation_params_with_reserve(self):
        expected_result = {
            "reserve": 20,
        }
        quota_descriptor = {
            "reserve": "20",
        }

        result = Ns._get_resource_allocation_params(
            quota_descriptor=quota_descriptor,
        )

        self.assertDictEqual(expected_result, result)

    def test__get_resource_allocation_params_with_shares(self):
        expected_result = {
            "shares": 30,
        }
        quota_descriptor = {
            "shares": "30",
        }

        result = Ns._get_resource_allocation_params(
            quota_descriptor=quota_descriptor,
        )

        self.assertDictEqual(expected_result, result)

    def test__get_resource_allocation_params(self):
        expected_result = {
            "limit": 10,
            "reserve": 20,
            "shares": 30,
        }
        quota_descriptor = {
            "limit": "10",
            "reserve": "20",
            "shares": "30",
        }

        result = Ns._get_resource_allocation_params(
            quota_descriptor=quota_descriptor,
        )

        self.assertDictEqual(expected_result, result)

    @patch("osm_ng_ro.ns.Ns._get_resource_allocation_params")
    def test__process_guest_epa_quota_params_with_empty_quota_epa_cpu(
        self,
        resource_allocation,
    ):
        expected_result = {}
        guest_epa_quota = {}
        epa_vcpu_set = True

        result = Ns._process_guest_epa_quota_params(
            guest_epa_quota=guest_epa_quota,
            epa_vcpu_set=epa_vcpu_set,
        )

        self.assertDictEqual(expected_result, result)
        self.assertFalse(resource_allocation.called)

    @patch("osm_ng_ro.ns.Ns._get_resource_allocation_params")
    def test__process_guest_epa_quota_params_with_empty_quota_false_epa_cpu(
        self,
        resource_allocation,
    ):
        expected_result = {}
        guest_epa_quota = {}
        epa_vcpu_set = False

        result = Ns._process_guest_epa_quota_params(
            guest_epa_quota=guest_epa_quota,
            epa_vcpu_set=epa_vcpu_set,
        )

        self.assertDictEqual(expected_result, result)
        self.assertFalse(resource_allocation.called)

    @patch("osm_ng_ro.ns.Ns._get_resource_allocation_params")
    def test__process_guest_epa_quota_params_with_wrong_quota_epa_cpu(
        self,
        resource_allocation,
    ):
        expected_result = {}
        guest_epa_quota = {
            "no-quota": "nothing",
        }
        epa_vcpu_set = True

        result = Ns._process_guest_epa_quota_params(
            guest_epa_quota=guest_epa_quota,
            epa_vcpu_set=epa_vcpu_set,
        )

        self.assertDictEqual(expected_result, result)
        self.assertFalse(resource_allocation.called)

    @patch("osm_ng_ro.ns.Ns._get_resource_allocation_params")
    def test__process_guest_epa_quota_params_with_wrong_quota_false_epa_cpu(
        self,
        resource_allocation,
    ):
        expected_result = {}
        guest_epa_quota = {
            "no-quota": "nothing",
        }
        epa_vcpu_set = False

        result = Ns._process_guest_epa_quota_params(
            guest_epa_quota=guest_epa_quota,
            epa_vcpu_set=epa_vcpu_set,
        )

        self.assertDictEqual(expected_result, result)
        self.assertFalse(resource_allocation.called)

    @patch("osm_ng_ro.ns.Ns._get_resource_allocation_params")
    def test__process_guest_epa_quota_params_with_cpu_quota_epa_cpu(
        self,
        resource_allocation,
    ):
        expected_result = {}
        guest_epa_quota = {
            "cpu-quota": {
                "limit": "10",
                "reserve": "20",
                "shares": "30",
            },
        }
        epa_vcpu_set = True

        result = Ns._process_guest_epa_quota_params(
            guest_epa_quota=guest_epa_quota,
            epa_vcpu_set=epa_vcpu_set,
        )

        self.assertDictEqual(expected_result, result)
        self.assertFalse(resource_allocation.called)

    @patch("osm_ng_ro.ns.Ns._get_resource_allocation_params")
    def test__process_guest_epa_quota_params_with_cpu_quota_false_epa_cpu(
        self,
        resource_allocation,
    ):
        expected_result = {
            "cpu-quota": {
                "limit": 10,
                "reserve": 20,
                "shares": 30,
            },
        }
        guest_epa_quota = {
            "cpu-quota": {
                "limit": "10",
                "reserve": "20",
                "shares": "30",
            },
        }
        epa_vcpu_set = False

        resource_allocation_param = {
            "limit": "10",
            "reserve": "20",
            "shares": "30",
        }
        resource_allocation.return_value = {
            "limit": 10,
            "reserve": 20,
            "shares": 30,
        }

        result = Ns._process_guest_epa_quota_params(
            guest_epa_quota=guest_epa_quota,
            epa_vcpu_set=epa_vcpu_set,
        )

        resource_allocation.assert_called_once_with(resource_allocation_param)
        self.assertDictEqual(expected_result, result)

    @patch("osm_ng_ro.ns.Ns._get_resource_allocation_params")
    def test__process_guest_epa_quota_params_with_mem_quota_epa_cpu(
        self,
        resource_allocation,
    ):
        expected_result = {
            "mem-quota": {
                "limit": 10,
                "reserve": 20,
                "shares": 30,
            },
        }
        guest_epa_quota = {
            "mem-quota": {
                "limit": "10",
                "reserve": "20",
                "shares": "30",
            },
        }
        epa_vcpu_set = True

        resource_allocation_param = {
            "limit": "10",
            "reserve": "20",
            "shares": "30",
        }
        resource_allocation.return_value = {
            "limit": 10,
            "reserve": 20,
            "shares": 30,
        }

        result = Ns._process_guest_epa_quota_params(
            guest_epa_quota=guest_epa_quota,
            epa_vcpu_set=epa_vcpu_set,
        )

        resource_allocation.assert_called_once_with(resource_allocation_param)
        self.assertDictEqual(expected_result, result)

    @patch("osm_ng_ro.ns.Ns._get_resource_allocation_params")
    def test__process_guest_epa_quota_params_with_mem_quota_false_epa_cpu(
        self,
        resource_allocation,
    ):
        expected_result = {
            "mem-quota": {
                "limit": 10,
                "reserve": 20,
                "shares": 30,
            },
        }
        guest_epa_quota = {
            "mem-quota": {
                "limit": "10",
                "reserve": "20",
                "shares": "30",
            },
        }
        epa_vcpu_set = False

        resource_allocation_param = {
            "limit": "10",
            "reserve": "20",
            "shares": "30",
        }
        resource_allocation.return_value = {
            "limit": 10,
            "reserve": 20,
            "shares": 30,
        }

        result = Ns._process_guest_epa_quota_params(
            guest_epa_quota=guest_epa_quota,
            epa_vcpu_set=epa_vcpu_set,
        )

        resource_allocation.assert_called_once_with(resource_allocation_param)
        self.assertDictEqual(expected_result, result)

    @patch("osm_ng_ro.ns.Ns._get_resource_allocation_params")
    def test__process_guest_epa_quota_params_with_disk_io_quota_epa_cpu(
        self,
        resource_allocation,
    ):
        expected_result = {
            "disk-io-quota": {
                "limit": 10,
                "reserve": 20,
                "shares": 30,
            },
        }
        guest_epa_quota = {
            "disk-io-quota": {
                "limit": "10",
                "reserve": "20",
                "shares": "30",
            },
        }
        epa_vcpu_set = True

        resource_allocation_param = {
            "limit": "10",
            "reserve": "20",
            "shares": "30",
        }
        resource_allocation.return_value = {
            "limit": 10,
            "reserve": 20,
            "shares": 30,
        }

        result = Ns._process_guest_epa_quota_params(
            guest_epa_quota=guest_epa_quota,
            epa_vcpu_set=epa_vcpu_set,
        )

        resource_allocation.assert_called_once_with(resource_allocation_param)
        self.assertDictEqual(expected_result, result)

    @patch("osm_ng_ro.ns.Ns._get_resource_allocation_params")
    def test__process_guest_epa_quota_params_with_disk_io_quota_false_epa_cpu(
        self,
        resource_allocation,
    ):
        expected_result = {
            "disk-io-quota": {
                "limit": 10,
                "reserve": 20,
                "shares": 30,
            },
        }
        guest_epa_quota = {
            "disk-io-quota": {
                "limit": "10",
                "reserve": "20",
                "shares": "30",
            },
        }
        epa_vcpu_set = False

        resource_allocation_param = {
            "limit": "10",
            "reserve": "20",
            "shares": "30",
        }
        resource_allocation.return_value = {
            "limit": 10,
            "reserve": 20,
            "shares": 30,
        }

        result = Ns._process_guest_epa_quota_params(
            guest_epa_quota=guest_epa_quota,
            epa_vcpu_set=epa_vcpu_set,
        )

        resource_allocation.assert_called_once_with(resource_allocation_param)
        self.assertDictEqual(expected_result, result)

    @patch("osm_ng_ro.ns.Ns._get_resource_allocation_params")
    def test__process_guest_epa_quota_params_with_vif_quota_epa_cpu(
        self,
        resource_allocation,
    ):
        expected_result = {
            "vif-quota": {
                "limit": 10,
                "reserve": 20,
                "shares": 30,
            },
        }
        guest_epa_quota = {
            "vif-quota": {
                "limit": "10",
                "reserve": "20",
                "shares": "30",
            },
        }
        epa_vcpu_set = True

        resource_allocation_param = {
            "limit": "10",
            "reserve": "20",
            "shares": "30",
        }
        resource_allocation.return_value = {
            "limit": 10,
            "reserve": 20,
            "shares": 30,
        }

        result = Ns._process_guest_epa_quota_params(
            guest_epa_quota=guest_epa_quota,
            epa_vcpu_set=epa_vcpu_set,
        )

        resource_allocation.assert_called_once_with(resource_allocation_param)
        self.assertDictEqual(expected_result, result)

    @patch("osm_ng_ro.ns.Ns._get_resource_allocation_params")
    def test__process_guest_epa_quota_params_with_vif_quota_false_epa_cpu(
        self,
        resource_allocation,
    ):
        expected_result = {
            "vif-quota": {
                "limit": 10,
                "reserve": 20,
                "shares": 30,
            },
        }
        guest_epa_quota = {
            "vif-quota": {
                "limit": "10",
                "reserve": "20",
                "shares": "30",
            },
        }
        epa_vcpu_set = False

        resource_allocation_param = {
            "limit": "10",
            "reserve": "20",
            "shares": "30",
        }
        resource_allocation.return_value = {
            "limit": 10,
            "reserve": 20,
            "shares": 30,
        }

        result = Ns._process_guest_epa_quota_params(
            guest_epa_quota=guest_epa_quota,
            epa_vcpu_set=epa_vcpu_set,
        )

        resource_allocation.assert_called_once_with(resource_allocation_param)
        self.assertDictEqual(expected_result, result)

    @patch("osm_ng_ro.ns.Ns._get_resource_allocation_params")
    def test__process_guest_epa_quota_params_with_quota_epa_cpu(
        self,
        resource_allocation,
    ):
        expected_result = {
            "mem-quota": {
                "limit": 10,
                "reserve": 20,
                "shares": 30,
            },
            "disk-io-quota": {
                "limit": 10,
                "reserve": 20,
                "shares": 30,
            },
            "vif-quota": {
                "limit": 10,
                "reserve": 20,
                "shares": 30,
            },
        }
        guest_epa_quota = {
            "cpu-quota": {
                "limit": "10",
                "reserve": "20",
                "shares": "30",
            },
            "mem-quota": {
                "limit": "10",
                "reserve": "20",
                "shares": "30",
            },
            "disk-io-quota": {
                "limit": "10",
                "reserve": "20",
                "shares": "30",
            },
            "vif-quota": {
                "limit": "10",
                "reserve": "20",
                "shares": "30",
            },
        }
        epa_vcpu_set = True

        resource_allocation.return_value = {
            "limit": 10,
            "reserve": 20,
            "shares": 30,
        }

        result = Ns._process_guest_epa_quota_params(
            guest_epa_quota=guest_epa_quota,
            epa_vcpu_set=epa_vcpu_set,
        )

        self.assertTrue(resource_allocation.called)
        self.assertDictEqual(expected_result, result)

    @patch("osm_ng_ro.ns.Ns._get_resource_allocation_params")
    def test__process_guest_epa_quota_params_with_quota_epa_cpu_no_set(
        self,
        resource_allocation,
    ):
        expected_result = {
            "cpu-quota": {
                "limit": 10,
                "reserve": 20,
                "shares": 30,
            },
            "mem-quota": {
                "limit": 10,
                "reserve": 20,
                "shares": 30,
            },
            "disk-io-quota": {
                "limit": 10,
                "reserve": 20,
                "shares": 30,
            },
            "vif-quota": {
                "limit": 10,
                "reserve": 20,
                "shares": 30,
            },
        }
        guest_epa_quota = {
            "cpu-quota": {
                "limit": "10",
                "reserve": "20",
                "shares": "30",
            },
            "mem-quota": {
                "limit": "10",
                "reserve": "20",
                "shares": "30",
            },
            "disk-io-quota": {
                "limit": "10",
                "reserve": "20",
                "shares": "30",
            },
            "vif-quota": {
                "limit": "10",
                "reserve": "20",
                "shares": "30",
            },
        }
        epa_vcpu_set = False

        resource_allocation.return_value = {
            "limit": 10,
            "reserve": 20,
            "shares": 30,
        }

        result = Ns._process_guest_epa_quota_params(
            guest_epa_quota=guest_epa_quota,
            epa_vcpu_set=epa_vcpu_set,
        )

        self.assertTrue(resource_allocation.called)
        self.assertDictEqual(expected_result, result)

    def test__process_guest_epa_numa_params_with_empty_numa_params(self):
        expected_numa_result = []
        expected_epa_vcpu_set_result = False
        guest_epa_quota = {}

        numa_result, epa_vcpu_set_result = Ns._process_guest_epa_numa_params(
            guest_epa_quota=guest_epa_quota,
        )
        self.assertEqual(expected_numa_result, numa_result)
        self.assertEqual(expected_epa_vcpu_set_result, epa_vcpu_set_result)

    def test__process_guest_epa_numa_params_with_wrong_numa_params(self):
        expected_numa_result = []
        expected_epa_vcpu_set_result = False
        guest_epa_quota = {"no_nume": "here"}

        numa_result, epa_vcpu_set_result = Ns._process_guest_epa_numa_params(
            guest_epa_quota=guest_epa_quota,
        )

        self.assertEqual(expected_numa_result, numa_result)
        self.assertEqual(expected_epa_vcpu_set_result, epa_vcpu_set_result)

    def test__process_guest_epa_numa_params_with_numa_node_policy(self):
        expected_numa_result = []
        expected_epa_vcpu_set_result = False
        guest_epa_quota = {"numa-node-policy": {}}

        numa_result, epa_vcpu_set_result = Ns._process_guest_epa_numa_params(
            guest_epa_quota=guest_epa_quota,
        )

        self.assertEqual(expected_numa_result, numa_result)
        self.assertEqual(expected_epa_vcpu_set_result, epa_vcpu_set_result)

    def test__process_guest_epa_numa_params_with_no_node(self):
        expected_numa_result = []
        expected_epa_vcpu_set_result = False
        guest_epa_quota = {
            "numa-node-policy": {
                "node": [],
            },
        }

        numa_result, epa_vcpu_set_result = Ns._process_guest_epa_numa_params(
            guest_epa_quota=guest_epa_quota,
        )

        self.assertEqual(expected_numa_result, numa_result)
        self.assertEqual(expected_epa_vcpu_set_result, epa_vcpu_set_result)

    def test__process_guest_epa_numa_params_with_1_node_num_cores(self):
        expected_numa_result = [{"cores": 3}]
        expected_epa_vcpu_set_result = True
        guest_epa_quota = {
            "numa-node-policy": {
                "node": [
                    {
                        "num-cores": 3,
                    },
                ],
            },
        }

        numa_result, epa_vcpu_set_result = Ns._process_guest_epa_numa_params(
            guest_epa_quota=guest_epa_quota,
        )

        self.assertEqual(expected_numa_result, numa_result)
        self.assertEqual(expected_epa_vcpu_set_result, epa_vcpu_set_result)

    def test__process_guest_epa_numa_params_with_1_node_paired_threads(self):
        expected_numa_result = [{"paired_threads": 3}]
        expected_epa_vcpu_set_result = True
        guest_epa_quota = {
            "numa-node-policy": {
                "node": [
                    {
                        "paired-threads": {"num-paired-threads": "3"},
                    },
                ],
            },
        }

        numa_result, epa_vcpu_set_result = Ns._process_guest_epa_numa_params(
            guest_epa_quota=guest_epa_quota,
        )

        self.assertEqual(expected_numa_result, numa_result)
        self.assertEqual(expected_epa_vcpu_set_result, epa_vcpu_set_result)

    def test__process_guest_epa_numa_params_with_1_node_paired_threads_ids(self):
        expected_numa_result = [
            {
                "paired-threads-id": [("0", "1"), ("4", "5")],
            }
        ]
        expected_epa_vcpu_set_result = False
        guest_epa_quota = {
            "numa-node-policy": {
                "node": [
                    {
                        "paired-threads": {
                            "paired-thread-ids": [
                                {
                                    "thread-a": 0,
                                    "thread-b": 1,
                                },
                                {
                                    "thread-a": 4,
                                    "thread-b": 5,
                                },
                            ],
                        },
                    },
                ],
            },
        }

        numa_result, epa_vcpu_set_result = Ns._process_guest_epa_numa_params(
            guest_epa_quota=guest_epa_quota,
        )

        self.assertEqual(expected_numa_result, numa_result)
        self.assertEqual(expected_epa_vcpu_set_result, epa_vcpu_set_result)

    def test__process_guest_epa_numa_params_with_1_node_num_threads(self):
        expected_numa_result = [{"threads": 3}]
        expected_epa_vcpu_set_result = True
        guest_epa_quota = {
            "numa-node-policy": {
                "node": [
                    {
                        "num-threads": "3",
                    },
                ],
            },
        }

        numa_result, epa_vcpu_set_result = Ns._process_guest_epa_numa_params(
            guest_epa_quota=guest_epa_quota,
        )

        self.assertEqual(expected_numa_result, numa_result)
        self.assertEqual(expected_epa_vcpu_set_result, epa_vcpu_set_result)

    def test__process_guest_epa_numa_params_with_1_node_memory_mb(self):
        expected_numa_result = [{"memory": 2}]
        expected_epa_vcpu_set_result = False
        guest_epa_quota = {
            "numa-node-policy": {
                "node": [
                    {
                        "memory-mb": 2048,
                    },
                ],
            },
        }

        numa_result, epa_vcpu_set_result = Ns._process_guest_epa_numa_params(
            guest_epa_quota=guest_epa_quota,
        )

        self.assertEqual(expected_numa_result, numa_result)
        self.assertEqual(expected_epa_vcpu_set_result, epa_vcpu_set_result)

    def test__process_guest_epa_numa_params_with_1_node_vcpu(self):
        expected_numa_result = [
            {
                "id": 0,
                "vcpu": [0, 1],
            }
        ]
        expected_epa_vcpu_set_result = False
        guest_epa_quota = {
            "numa-node-policy": {
                "node": [{"id": "0", "vcpu": [{"id": "0"}, {"id": "1"}]}],
            },
        }

        numa_result, epa_vcpu_set_result = Ns._process_guest_epa_numa_params(
            guest_epa_quota=guest_epa_quota,
        )

        self.assertEqual(expected_numa_result, numa_result)
        self.assertEqual(expected_epa_vcpu_set_result, epa_vcpu_set_result)

    def test__process_guest_epa_numa_params_with_2_node_vcpu(self):
        expected_numa_result = [
            {
                "id": 0,
                "vcpu": [0, 1],
            },
            {
                "id": 1,
                "vcpu": [2, 3],
            },
        ]

        expected_epa_vcpu_set_result = False
        guest_epa_quota = {
            "numa-node-policy": {
                "node": [
                    {"id": "0", "vcpu": [{"id": "0"}, {"id": "1"}]},
                    {"id": "1", "vcpu": [{"id": "2"}, {"id": "3"}]},
                ],
            },
        }

        numa_result, epa_vcpu_set_result = Ns._process_guest_epa_numa_params(
            guest_epa_quota=guest_epa_quota,
        )

        self.assertEqual(expected_numa_result, numa_result)
        self.assertEqual(expected_epa_vcpu_set_result, epa_vcpu_set_result)

    def test__process_guest_epa_numa_params_with_1_node(self):
        expected_numa_result = [
            {
                # "id": 0,
                # "vcpu": [0, 1],
                "cores": 3,
                "paired_threads": 3,
                "paired-threads-id": [("0", "1"), ("4", "5")],
                "threads": 3,
                "memory": 2,
            }
        ]
        expected_epa_vcpu_set_result = True
        guest_epa_quota = {
            "numa-node-policy": {
                "node": [
                    {
                        "num-cores": 3,
                        "paired-threads": {
                            "num-paired-threads": "3",
                            "paired-thread-ids": [
                                {
                                    "thread-a": 0,
                                    "thread-b": 1,
                                },
                                {
                                    "thread-a": 4,
                                    "thread-b": 5,
                                },
                            ],
                        },
                        "num-threads": "3",
                        "memory-mb": 2048,
                    },
                ],
            },
        }

        numa_result, epa_vcpu_set_result = Ns._process_guest_epa_numa_params(
            guest_epa_quota=guest_epa_quota,
        )

        self.assertEqual(expected_numa_result, numa_result)
        self.assertEqual(expected_epa_vcpu_set_result, epa_vcpu_set_result)

    def test__process_guest_epa_numa_params_with_2_nodes(self):
        expected_numa_result = [
            {
                "cores": 3,
                "paired_threads": 3,
                "paired-threads-id": [("0", "1"), ("4", "5")],
                "threads": 3,
                "memory": 2,
            },
            {
                "cores": 7,
                "paired_threads": 7,
                "paired-threads-id": [("2", "3"), ("5", "6")],
                "threads": 4,
                "memory": 4,
            },
        ]
        expected_epa_vcpu_set_result = True
        guest_epa_quota = {
            "numa-node-policy": {
                "node": [
                    {
                        "num-cores": 3,
                        "paired-threads": {
                            "num-paired-threads": "3",
                            "paired-thread-ids": [
                                {
                                    "thread-a": 0,
                                    "thread-b": 1,
                                },
                                {
                                    "thread-a": 4,
                                    "thread-b": 5,
                                },
                            ],
                        },
                        "num-threads": "3",
                        "memory-mb": 2048,
                    },
                    {
                        "num-cores": 7,
                        "paired-threads": {
                            "num-paired-threads": "7",
                            "paired-thread-ids": [
                                {
                                    "thread-a": 2,
                                    "thread-b": 3,
                                },
                                {
                                    "thread-a": 5,
                                    "thread-b": 6,
                                },
                            ],
                        },
                        "num-threads": "4",
                        "memory-mb": 4096,
                    },
                ],
            },
        }

        numa_result, epa_vcpu_set_result = Ns._process_guest_epa_numa_params(
            guest_epa_quota=guest_epa_quota,
        )

        self.assertEqual(expected_numa_result, numa_result)
        self.assertEqual(expected_epa_vcpu_set_result, epa_vcpu_set_result)

    def test__process_guest_epa_cpu_pinning_params_with_empty_params(self):
        expected_numa_result = {}
        expected_epa_vcpu_set_result = False
        guest_epa_quota = {}
        vcpu_count = 0
        epa_vcpu_set = False

        numa_result, epa_vcpu_set_result = Ns._process_guest_epa_cpu_pinning_params(
            guest_epa_quota=guest_epa_quota,
            vcpu_count=vcpu_count,
            epa_vcpu_set=epa_vcpu_set,
        )

        self.assertDictEqual(expected_numa_result, numa_result)
        self.assertEqual(expected_epa_vcpu_set_result, epa_vcpu_set_result)

    def test__process_guest_epa_cpu_pinning_params_with_wrong_params(self):
        expected_numa_result = {}
        expected_epa_vcpu_set_result = False
        guest_epa_quota = {
            "no-cpu-pinning-policy": "here",
        }
        vcpu_count = 0
        epa_vcpu_set = False

        numa_result, epa_vcpu_set_result = Ns._process_guest_epa_cpu_pinning_params(
            guest_epa_quota=guest_epa_quota,
            vcpu_count=vcpu_count,
            epa_vcpu_set=epa_vcpu_set,
        )

        self.assertDictEqual(expected_numa_result, numa_result)
        self.assertEqual(expected_epa_vcpu_set_result, epa_vcpu_set_result)

    def test__process_guest_epa_cpu_pinning_params_with_epa_vcpu_set(self):
        expected_numa_result = {}
        expected_epa_vcpu_set_result = True
        guest_epa_quota = {
            "cpu-pinning-policy": "DEDICATED",
        }
        vcpu_count = 0
        epa_vcpu_set = True

        numa_result, epa_vcpu_set_result = Ns._process_guest_epa_cpu_pinning_params(
            guest_epa_quota=guest_epa_quota,
            vcpu_count=vcpu_count,
            epa_vcpu_set=epa_vcpu_set,
        )

        self.assertDictEqual(expected_numa_result, numa_result)
        self.assertEqual(expected_epa_vcpu_set_result, epa_vcpu_set_result)

    def test__process_guest_epa_cpu_pinning_params_with_policy_prefer(self):
        expected_numa_result = {"threads": 3}
        expected_epa_vcpu_set_result = True
        guest_epa_quota = {
            "cpu-pinning-policy": "DEDICATED",
            "cpu-thread-pinning-policy": "PREFER",
        }
        vcpu_count = 3
        epa_vcpu_set = False

        numa_result, epa_vcpu_set_result = Ns._process_guest_epa_cpu_pinning_params(
            guest_epa_quota=guest_epa_quota,
            vcpu_count=vcpu_count,
            epa_vcpu_set=epa_vcpu_set,
        )

        self.assertDictEqual(expected_numa_result, numa_result)
        self.assertEqual(expected_epa_vcpu_set_result, epa_vcpu_set_result)

    def test__process_guest_epa_cpu_pinning_params_with_policy_isolate(self):
        expected_numa_result = {"cores": 3}
        expected_epa_vcpu_set_result = True
        guest_epa_quota = {
            "cpu-pinning-policy": "DEDICATED",
            "cpu-thread-pinning-policy": "ISOLATE",
        }
        vcpu_count = 3
        epa_vcpu_set = False

        numa_result, epa_vcpu_set_result = Ns._process_guest_epa_cpu_pinning_params(
            guest_epa_quota=guest_epa_quota,
            vcpu_count=vcpu_count,
            epa_vcpu_set=epa_vcpu_set,
        )

        self.assertDictEqual(expected_numa_result, numa_result)
        self.assertEqual(expected_epa_vcpu_set_result, epa_vcpu_set_result)

    def test__process_guest_epa_cpu_pinning_params_with_policy_require(self):
        expected_numa_result = {"threads": 3}
        expected_epa_vcpu_set_result = True
        guest_epa_quota = {
            "cpu-pinning-policy": "DEDICATED",
            "cpu-thread-pinning-policy": "REQUIRE",
        }
        vcpu_count = 3
        epa_vcpu_set = False

        numa_result, epa_vcpu_set_result = Ns._process_guest_epa_cpu_pinning_params(
            guest_epa_quota=guest_epa_quota,
            vcpu_count=vcpu_count,
            epa_vcpu_set=epa_vcpu_set,
        )

        self.assertDictEqual(expected_numa_result, numa_result)
        self.assertEqual(expected_epa_vcpu_set_result, epa_vcpu_set_result)

    def test__process_guest_epa_cpu_pinning_params(self):
        expected_numa_result = {"threads": 3}
        expected_epa_vcpu_set_result = True
        guest_epa_quota = {
            "cpu-pinning-policy": "DEDICATED",
        }
        vcpu_count = 3
        epa_vcpu_set = False

        numa_result, epa_vcpu_set_result = Ns._process_guest_epa_cpu_pinning_params(
            guest_epa_quota=guest_epa_quota,
            vcpu_count=vcpu_count,
            epa_vcpu_set=epa_vcpu_set,
        )

        self.assertDictEqual(expected_numa_result, numa_result)
        self.assertEqual(expected_epa_vcpu_set_result, epa_vcpu_set_result)

    @patch("osm_ng_ro.ns.Ns._process_guest_epa_quota_params")
    @patch("osm_ng_ro.ns.Ns._process_guest_epa_cpu_pinning_params")
    @patch("osm_ng_ro.ns.Ns._process_guest_epa_numa_params")
    def test__process_guest_epa_params_with_empty_params(
        self,
        guest_epa_numa_params,
        guest_epa_cpu_pinning_params,
        guest_epa_quota_params,
    ):
        expected_result = {}
        target_flavor = {}

        result = Ns._process_epa_params(
            target_flavor=target_flavor,
        )

        self.assertDictEqual(expected_result, result)
        self.assertFalse(guest_epa_numa_params.called)
        self.assertFalse(guest_epa_cpu_pinning_params.called)
        self.assertFalse(guest_epa_quota_params.called)

    @patch("osm_ng_ro.ns.Ns._process_guest_epa_quota_params")
    @patch("osm_ng_ro.ns.Ns._process_guest_epa_cpu_pinning_params")
    @patch("osm_ng_ro.ns.Ns._process_guest_epa_numa_params")
    def test__process_guest_epa_params_with_wrong_params(
        self,
        guest_epa_numa_params,
        guest_epa_cpu_pinning_params,
        guest_epa_quota_params,
    ):
        expected_result = {}
        target_flavor = {
            "no-guest-epa": "here",
        }

        result = Ns._process_epa_params(
            target_flavor=target_flavor,
        )

        self.assertDictEqual(expected_result, result)
        self.assertFalse(guest_epa_numa_params.called)
        self.assertFalse(guest_epa_cpu_pinning_params.called)
        self.assertFalse(guest_epa_quota_params.called)

    @patch("osm_ng_ro.ns.Ns._process_guest_epa_quota_params")
    @patch("osm_ng_ro.ns.Ns._process_guest_epa_cpu_pinning_params")
    @patch("osm_ng_ro.ns.Ns._process_guest_epa_numa_params")
    def test__process_guest_epa_params(
        self,
        guest_epa_numa_params,
        guest_epa_cpu_pinning_params,
        guest_epa_quota_params,
    ):
        expected_result = {
            "mem-policy": "STRICT",
        }
        target_flavor = {
            "guest-epa": {
                "vcpu-count": 1,
                "numa-node-policy": {
                    "mem-policy": "STRICT",
                },
            },
        }

        guest_epa_numa_params.return_value = ({}, False)
        guest_epa_cpu_pinning_params.return_value = ({}, False)
        guest_epa_quota_params.return_value = {}

        result = Ns._process_epa_params(
            target_flavor=target_flavor,
        )

        self.assertDictEqual(expected_result, result)
        self.assertTrue(guest_epa_numa_params.called)
        self.assertTrue(guest_epa_cpu_pinning_params.called)
        self.assertTrue(guest_epa_quota_params.called)

    @patch("osm_ng_ro.ns.Ns._process_guest_epa_quota_params")
    @patch("osm_ng_ro.ns.Ns._process_guest_epa_cpu_pinning_params")
    @patch("osm_ng_ro.ns.Ns._process_guest_epa_numa_params")
    def test__process_guest_epa_params_with_mempage_size(
        self,
        guest_epa_numa_params,
        guest_epa_cpu_pinning_params,
        guest_epa_quota_params,
    ):
        expected_result = {
            "mempage-size": "1G",
            "mem-policy": "STRICT",
        }
        target_flavor = {
            "guest-epa": {
                "vcpu-count": 1,
                "mempage-size": "1G",
                "numa-node-policy": {
                    "mem-policy": "STRICT",
                },
            },
        }

        guest_epa_numa_params.return_value = ({}, False)
        guest_epa_cpu_pinning_params.return_value = ({}, False)
        guest_epa_quota_params.return_value = {}

        result = Ns._process_epa_params(
            target_flavor=target_flavor,
        )

        self.assertDictEqual(expected_result, result)
        self.assertTrue(guest_epa_numa_params.called)
        self.assertTrue(guest_epa_cpu_pinning_params.called)
        self.assertTrue(guest_epa_quota_params.called)

    @patch("osm_ng_ro.ns.Ns._process_guest_epa_quota_params")
    @patch("osm_ng_ro.ns.Ns._process_guest_epa_cpu_pinning_params")
    @patch("osm_ng_ro.ns.Ns._process_guest_epa_numa_params")
    def test__process_guest_epa_params_with_numa(
        self,
        guest_epa_numa_params,
        guest_epa_cpu_pinning_params,
        guest_epa_quota_params,
    ):
        expected_result = {
            "mempage-size": "1G",
            "cpu-pinning-policy": "DEDICATED",
            "cpu-thread-pinning-policy": "PREFER",
            "numas": [
                {
                    "cores": 3,
                    "memory": 2,
                    "paired-threads": 3,
                    "paired-threads-id": [("0", "1"), ("4", "5")],
                    "threads": 3,
                }
            ],
            "cpu-quota": {"limit": 10, "reserve": 20, "shares": 30},
            "disk-io-quota": {"limit": 10, "reserve": 20, "shares": 30},
            "mem-quota": {"limit": 10, "reserve": 20, "shares": 30},
            "vif-quota": {"limit": 10, "reserve": 20, "shares": 30},
        }
        target_flavor = {
            "guest-epa": {
                "vcpu-count": 1,
                "mempage-size": "1G",
                "cpu-pinning-policy": "DEDICATED",
                "cpu-thread-pinning-policy": "PREFER",
                "numa-node-policy": {
                    "node": [
                        {
                            "num-cores": 3,
                            "paired-threads": {
                                "num-paired-threads": "3",
                                "paired-thread-ids": [
                                    {
                                        "thread-a": 0,
                                        "thread-b": 1,
                                    },
                                    {
                                        "thread-a": 4,
                                        "thread-b": 5,
                                    },
                                ],
                            },
                            "num-threads": "3",
                            "memory-mb": 2048,
                        },
                    ],
                },
                "cpu-quota": {
                    "limit": "10",
                    "reserve": "20",
                    "shares": "30",
                },
                "mem-quota": {
                    "limit": "10",
                    "reserve": "20",
                    "shares": "30",
                },
                "disk-io-quota": {
                    "limit": "10",
                    "reserve": "20",
                    "shares": "30",
                },
                "vif-quota": {
                    "limit": "10",
                    "reserve": "20",
                    "shares": "30",
                },
            },
        }

        guest_epa_numa_params.return_value = (
            [
                {
                    "cores": 3,
                    "paired-threads": 3,
                    "paired-threads-id": [("0", "1"), ("4", "5")],
                    "threads": 3,
                    "memory": 2,
                },
            ],
            True,
        )
        guest_epa_cpu_pinning_params.return_value = (
            {
                "threads": 3,
            },
            True,
        )
        guest_epa_quota_params.return_value = {
            "cpu-quota": {
                "limit": 10,
                "reserve": 20,
                "shares": 30,
            },
            "mem-quota": {
                "limit": 10,
                "reserve": 20,
                "shares": 30,
            },
            "disk-io-quota": {
                "limit": 10,
                "reserve": 20,
                "shares": 30,
            },
            "vif-quota": {
                "limit": 10,
                "reserve": 20,
                "shares": 30,
            },
        }

        result = Ns._process_epa_params(
            target_flavor=target_flavor,
        )
        self.assertEqual(expected_result, result)
        self.assertTrue(guest_epa_numa_params.called)
        self.assertTrue(guest_epa_cpu_pinning_params.called)
        self.assertTrue(guest_epa_quota_params.called)

    @patch("osm_ng_ro.ns.Ns._process_epa_params")
    def test__process_flavor_params_with_empty_target_flavor(
        self,
        epa_params,
    ):
        target_flavor = {}
        indata = {
            "vnf": [
                {
                    "vnfd-id": "ad6356e3-698c-43bf-9901-3aae9e9b9d18",
                },
            ],
        }
        vim_info = {}
        target_record_id = ""

        with self.assertRaises(KeyError):
            Ns._process_flavor_params(
                target_flavor=target_flavor,
                indata=indata,
                vim_info=vim_info,
                target_record_id=target_record_id,
            )

        self.assertFalse(epa_params.called)

    @patch("osm_ng_ro.ns.Ns._process_epa_params")
    def test__process_flavor_params_with_wrong_target_flavor(
        self,
        epa_params,
    ):
        target_flavor = {
            "no-target-flavor": "here",
        }
        indata = {}
        vim_info = {}
        target_record_id = ""

        with self.assertRaises(KeyError):
            Ns._process_flavor_params(
                target_flavor=target_flavor,
                indata=indata,
                vim_info=vim_info,
                target_record_id=target_record_id,
            )

        self.assertFalse(epa_params.called)

    @patch("osm_ng_ro.ns.Ns._process_epa_params")
    def test__process_flavor_params_with_empty_indata(
        self,
        epa_params,
    ):
        expected_result = {
            "find_params": {
                "flavor_data": {
                    "disk": 10,
                    "ram": 1024,
                    "vcpus": 2,
                },
            },
            "params": {
                "flavor_data": {
                    "disk": 10,
                    "name": "test",
                    "ram": 1024,
                    "vcpus": 2,
                },
            },
        }
        target_flavor = {
            "name": "test",
            "storage-gb": "10",
            "memory-mb": "1024",
            "vcpu-count": "2",
        }
        indata = {}
        vim_info = {}
        target_record_id = ""

        epa_params.return_value = {}

        result = Ns._process_flavor_params(
            target_flavor=target_flavor,
            indata=indata,
            vim_info=vim_info,
            target_record_id=target_record_id,
        )

        self.assertTrue(epa_params.called)
        self.assertDictEqual(result, expected_result)

    @patch("osm_ng_ro.ns.Ns._process_epa_params")
    def test__process_flavor_params_with_wrong_indata(
        self,
        epa_params,
    ):
        expected_result = {
            "find_params": {
                "flavor_data": {
                    "disk": 10,
                    "ram": 1024,
                    "vcpus": 2,
                },
            },
            "params": {
                "flavor_data": {
                    "disk": 10,
                    "name": "test",
                    "ram": 1024,
                    "vcpus": 2,
                },
            },
        }
        target_flavor = {
            "name": "test",
            "storage-gb": "10",
            "memory-mb": "1024",
            "vcpu-count": "2",
        }
        indata = {
            "no-vnf": "here",
        }
        vim_info = {}
        target_record_id = ""

        epa_params.return_value = {}

        result = Ns._process_flavor_params(
            target_flavor=target_flavor,
            indata=indata,
            vim_info=vim_info,
            target_record_id=target_record_id,
        )

        self.assertTrue(epa_params.called)
        self.assertDictEqual(result, expected_result)

    @patch("osm_ng_ro.ns.Ns._process_epa_params")
    def test__process_flavor_params_with_ephemeral_disk(
        self,
        epa_params,
    ):
        kwargs = {
            "db": db,
        }

        db.get_one.return_value = {
            "_id": "ad6356e3-698c-43bf-9901-3aae9e9b9d18",
            "df": [
                {
                    "id": "default-df",
                    "vdu-profile": [
                        {"id": "without_volumes-VM", "min-number-of-instances": 1}
                    ],
                }
            ],
            "id": "without_volumes-vnf",
            "product-name": "without_volumes-vnf",
            "vdu": [
                {
                    "id": "without_volumes-VM",
                    "name": "without_volumes-VM",
                    "sw-image-desc": "ubuntu20.04",
                    "alternative-sw-image-desc": [
                        "ubuntu20.04-aws",
                        "ubuntu20.04-azure",
                    ],
                    "virtual-storage-desc": ["root-volume", "ephemeral-volume"],
                }
            ],
            "version": "1.0",
            "virtual-storage-desc": [
                {"id": "root-volume", "size-of-storage": "10"},
                {
                    "id": "ephemeral-volume",
                    "type-of-storage": "etsi-nfv-descriptors:ephemeral-storage",
                    "size-of-storage": "1",
                },
            ],
            "_admin": {
                "storage": {
                    "fs": "mongo",
                    "path": "/app/storage/",
                },
                "type": "vnfd",
            },
        }
        expected_result = {
            "find_params": {
                "flavor_data": {
                    "disk": 10,
                    "ram": 1024,
                    "vcpus": 2,
                    "ephemeral": 10,
                },
            },
            "params": {
                "flavor_data": {
                    "disk": 10,
                    "name": "test",
                    "ram": 1024,
                    "vcpus": 2,
                    "ephemeral": 10,
                },
            },
        }
        target_flavor = {
            "id": "test_id",
            "name": "test",
            "storage-gb": "10",
            "memory-mb": "1024",
            "vcpu-count": "2",
        }
        indata = {
            "vnf": [
                {
                    "vdur": [
                        {
                            "ns-flavor-id": "test_id",
                            "virtual-storages": [
                                {
                                    "type-of-storage": "etsi-nfv-descriptors:ephemeral-storage",
                                    "size-of-storage": "10",
                                },
                            ],
                        },
                    ],
                    "vnfd-id": "ad6356e3-698c-43bf-9901-3aae9e9b9d18",
                },
            ],
        }
        vim_info = {}
        target_record_id = ""

        epa_params.return_value = {}

        result = Ns._process_flavor_params(
            target_flavor=target_flavor,
            indata=indata,
            vim_info=vim_info,
            target_record_id=target_record_id,
            **kwargs,
        )

        self.assertTrue(epa_params.called)
        self.assertDictEqual(result, expected_result)

    @patch("osm_ng_ro.ns.Ns._process_epa_params")
    def test__process_flavor_params_with_swap_disk(
        self,
        epa_params,
    ):
        expected_result = {
            "find_params": {
                "flavor_data": {
                    "disk": 10,
                    "ram": 1024,
                    "vcpus": 2,
                    "swap": 20,
                },
            },
            "params": {
                "flavor_data": {
                    "disk": 10,
                    "name": "test",
                    "ram": 1024,
                    "vcpus": 2,
                    "swap": 20,
                },
            },
        }
        target_flavor = {
            "id": "test_id",
            "name": "test",
            "storage-gb": "10",
            "memory-mb": "1024",
            "vcpu-count": "2",
        }
        indata = {
            "vnf": [
                {
                    "vdur": [
                        {
                            "ns-flavor-id": "test_id",
                            "virtual-storages": [
                                {
                                    "type-of-storage": "etsi-nfv-descriptors:swap-storage",
                                    "size-of-storage": "20",
                                },
                            ],
                        },
                    ],
                    "vnfd-id": "ad6356e3-698c-43bf-9901-3aae9e9b9d18",
                },
            ],
        }
        vim_info = {}
        target_record_id = ""

        epa_params.return_value = {}

        result = Ns._process_flavor_params(
            target_flavor=target_flavor,
            indata=indata,
            vim_info=vim_info,
            target_record_id=target_record_id,
        )

        self.assertTrue(epa_params.called)
        self.assertDictEqual(result, expected_result)

    @patch("osm_ng_ro.ns.Ns._process_epa_params")
    def test__process_flavor_params_with_persistent_root_disk(
        self,
        epa_params,
    ):
        kwargs = {
            "db": db,
        }

        db.get_one.return_value = {
            "_id": "ad6356e3-698c-43bf-9901-3aae9e9b9d18",
            "df": [
                {
                    "id": "default-df",
                    "vdu-profile": [
                        {"id": "several_volumes-VM", "min-number-of-instances": 1}
                    ],
                }
            ],
            "id": "several_volumes-vnf",
            "product-name": "several_volumes-vnf",
            "vdu": [
                {
                    "id": "several_volumes-VM",
                    "name": "several_volumes-VM",
                    "sw-image-desc": "ubuntu20.04",
                    "alternative-sw-image-desc": [
                        "ubuntu20.04-aws",
                        "ubuntu20.04-azure",
                    ],
                    "virtual-storage-desc": [
                        "persistent-root-volume",
                    ],
                }
            ],
            "version": "1.0",
            "virtual-storage-desc": [
                {
                    "id": "persistent-root-volume",
                    "type-of-storage": "persistent-storage:persistent-storage",
                    "size-of-storage": "10",
                },
            ],
            "_admin": {
                "storage": {
                    "fs": "mongo",
                    "path": "/app/storage/",
                },
                "type": "vnfd",
            },
        }
        expected_result = {
            "find_params": {
                "flavor_data": {
                    "disk": 0,
                    "ram": 1024,
                    "vcpus": 2,
                },
            },
            "params": {
                "flavor_data": {
                    "disk": 0,
                    "name": "test",
                    "ram": 1024,
                    "vcpus": 2,
                },
            },
        }
        target_flavor = {
            "id": "test_id",
            "name": "test",
            "storage-gb": "10",
            "memory-mb": "1024",
            "vcpu-count": "2",
        }
        indata = {
            "vnf": [
                {
                    "vdur": [
                        {
                            "vdu-name": "several_volumes-VM",
                            "ns-flavor-id": "test_id",
                            "virtual-storages": [
                                {
                                    "type-of-storage": "persistent-storage:persistent-storage",
                                    "size-of-storage": "10",
                                },
                            ],
                        },
                    ],
                    "vnfd-id": "ad6356e3-698c-43bf-9901-3aae9e9b9d18",
                },
            ],
        }
        vim_info = {}
        target_record_id = ""

        epa_params.return_value = {}

        result = Ns._process_flavor_params(
            target_flavor=target_flavor,
            indata=indata,
            vim_info=vim_info,
            target_record_id=target_record_id,
            **kwargs,
        )

        self.assertTrue(epa_params.called)
        self.assertDictEqual(result, expected_result)

    @patch("osm_ng_ro.ns.Ns._process_epa_params")
    def test__process_flavor_params_with_epa_params(
        self,
        epa_params,
    ):
        expected_result = {
            "find_params": {
                "flavor_data": {
                    "disk": 10,
                    "ram": 1024,
                    "vcpus": 2,
                    "extended": {
                        "numa": "there-is-numa-here",
                    },
                },
            },
            "params": {
                "flavor_data": {
                    "disk": 10,
                    "name": "test",
                    "ram": 1024,
                    "vcpus": 2,
                    "extended": {
                        "numa": "there-is-numa-here",
                    },
                },
            },
        }
        target_flavor = {
            "id": "test_id",
            "name": "test",
            "storage-gb": "10",
            "memory-mb": "1024",
            "vcpu-count": "2",
        }
        indata = {
            "vnf": [
                {
                    "vdur": [
                        {
                            "ns-flavor-id": "test_id",
                        },
                    ],
                    "vnfd-id": "ad6356e3-698c-43bf-9901-3aae9e9b9d18",
                },
            ],
        }
        vim_info = {}
        target_record_id = ""

        epa_params.return_value = {
            "numa": "there-is-numa-here",
        }

        result = Ns._process_flavor_params(
            target_flavor=target_flavor,
            indata=indata,
            vim_info=vim_info,
            target_record_id=target_record_id,
        )

        self.assertTrue(epa_params.called)
        self.assertDictEqual(result, expected_result)

    @patch("osm_ng_ro.ns.Ns._process_epa_params")
    def test__process_flavor_params_with_vim_flavor_id(
        self,
        epa_params,
    ):
        expected_result = {
            "find_params": {
                "vim_flavor_id": "test.flavor",
            },
        }
        target_flavor = {
            "id": "test_id",
            "name": "test",
            "storage-gb": "10",
            "memory-mb": "1024",
            "vcpu-count": "2",
        }
        indata = {
            "vnf": [
                {
                    "vdur": [
                        {
                            "ns-flavor-id": "test_id",
                            "additionalParams": {
                                "OSM": {"vim_flavor_id": "test.flavor"}
                            },
                        },
                    ],
                    "vnfd-id": "ad6356e3-698c-43bf-9901-3aae9e9b9d18",
                },
            ],
        }
        vim_info = {}
        target_record_id = ""

        epa_params.return_value = {}

        result = Ns._process_flavor_params(
            target_flavor=target_flavor,
            indata=indata,
            vim_info=vim_info,
            target_record_id=target_record_id,
        )

        self.assertFalse(epa_params.called)
        self.assertDictEqual(result, expected_result)

    @patch("osm_ng_ro.ns.Ns._process_epa_params")
    def test__process_flavor_params(
        self,
        epa_params,
    ):
        kwargs = {
            "db": db,
        }

        db.get_one.return_value = {
            "_id": "ad6356e3-698c-43bf-9901-3aae9e9b9d18",
            "df": [
                {
                    "id": "default-df",
                    "vdu-profile": [
                        {"id": "without_volumes-VM", "min-number-of-instances": 1}
                    ],
                }
            ],
            "id": "without_volumes-vnf",
            "product-name": "without_volumes-vnf",
            "vdu": [
                {
                    "id": "without_volumes-VM",
                    "name": "without_volumes-VM",
                    "sw-image-desc": "ubuntu20.04",
                    "alternative-sw-image-desc": [
                        "ubuntu20.04-aws",
                        "ubuntu20.04-azure",
                    ],
                    "virtual-storage-desc": ["root-volume", "ephemeral-volume"],
                }
            ],
            "version": "1.0",
            "virtual-storage-desc": [
                {"id": "root-volume", "size-of-storage": "10"},
                {
                    "id": "ephemeral-volume",
                    "type-of-storage": "etsi-nfv-descriptors:ephemeral-storage",
                    "size-of-storage": "1",
                },
            ],
            "_admin": {
                "storage": {
                    "fs": "mongo",
                    "path": "/app/storage/",
                },
                "type": "vnfd",
            },
        }

        expected_result = {
            "find_params": {
                "flavor_data": {
                    "disk": 10,
                    "ram": 1024,
                    "vcpus": 2,
                    "ephemeral": 10,
                    "swap": 20,
                    "extended": {
                        "numa": "there-is-numa-here",
                    },
                },
            },
            "params": {
                "flavor_data": {
                    "disk": 10,
                    "name": "test",
                    "ram": 1024,
                    "vcpus": 2,
                    "ephemeral": 10,
                    "swap": 20,
                    "extended": {
                        "numa": "there-is-numa-here",
                    },
                },
            },
        }
        target_flavor = {
            "id": "test_id",
            "name": "test",
            "storage-gb": "10",
            "memory-mb": "1024",
            "vcpu-count": "2",
        }
        indata = {
            "vnf": [
                {
                    "vdur": [
                        {
                            "ns-flavor-id": "test_id",
                            "virtual-storages": [
                                {
                                    "type-of-storage": "etsi-nfv-descriptors:ephemeral-storage",
                                    "size-of-storage": "10",
                                },
                                {
                                    "type-of-storage": "etsi-nfv-descriptors:swap-storage",
                                    "size-of-storage": "20",
                                },
                            ],
                        },
                    ],
                    "vnfd-id": "ad6356e3-698c-43bf-9901-3aae9e9b9d18",
                },
            ],
        }
        vim_info = {}
        target_record_id = ""

        epa_params.return_value = {
            "numa": "there-is-numa-here",
        }

        result = Ns._process_flavor_params(
            target_flavor=target_flavor,
            indata=indata,
            vim_info=vim_info,
            target_record_id=target_record_id,
            **kwargs,
        )

        self.assertTrue(epa_params.called)
        self.assertDictEqual(result, expected_result)

    def test__process_net_params_with_empty_params(
        self,
    ):
        target_vld = {
            "name": "vld-name",
        }
        indata = {
            "name": "ns-name",
        }
        vim_info = {
            "provider_network": "some-profile-here",
            "ip_profile": {
                "some_ip_profile": "here",
            },
        }
        target_record_id = ""
        expected_result = {
            "params": {
                "net_name": "ns-name-vld-name",
                "net_type": "bridge",
                "ip_profile": {
                    "some_ip_profile": "here",
                },
                "provider_network_profile": "some-profile-here",
            }
        }

        result = Ns._process_net_params(
            target_vld=target_vld,
            indata=indata,
            vim_info=vim_info,
            target_record_id=target_record_id,
        )

        self.assertDictEqual(expected_result, result)

    def test__process_net_params_with_vim_info_sdn(
        self,
    ):
        target_vld = {
            "name": "vld-name",
        }
        indata = {
            "name": "ns-name",
        }
        vim_info = {
            "sdn": "some-sdn",
            "sdn-ports": ["some", "ports", "here"],
            "vlds": ["some", "vlds", "here"],
            "type": "sdn-type",
        }
        target_record_id = "vld.sdn.something"
        expected_result = {
            "params": {
                "sdn-ports": ["some", "ports", "here"],
                "vlds": ["some", "vlds", "here"],
                "type": "sdn-type",
            }
        }

        result = Ns._process_net_params(
            target_vld=target_vld,
            indata=indata,
            vim_info=vim_info,
            target_record_id=target_record_id,
        )

        self.assertDictEqual(expected_result, result)

    def test__process_net_params_with_vim_info_sdn_target_vim(
        self,
    ):
        target_vld = {
            "name": "vld-name",
        }
        indata = {
            "name": "ns-name",
        }
        vim_info = {
            "sdn": "some-sdn",
            "sdn-ports": ["some", "ports", "here"],
            "vlds": ["some", "vlds", "here"],
            "target_vim": "some-vim",
            "type": "sdn-type",
        }
        target_record_id = "vld.sdn.something"
        expected_result = {
            "depends_on": ["some-vim vld.sdn"],
            "params": {
                "sdn-ports": ["some", "ports", "here"],
                "vlds": ["some", "vlds", "here"],
                "target_vim": "some-vim",
                "type": "sdn-type",
            },
        }

        result = Ns._process_net_params(
            target_vld=target_vld,
            indata=indata,
            vim_info=vim_info,
            target_record_id=target_record_id,
        )

        self.assertDictEqual(expected_result, result)

    def test__process_net_params_with_vim_network_name(
        self,
    ):
        target_vld = {
            "name": "vld-name",
        }
        indata = {
            "name": "ns-name",
        }
        vim_info = {
            "vim_network_name": "some-network-name",
        }
        target_record_id = "vld.sdn.something"
        expected_result = {
            "find_params": {
                "filter_dict": {
                    "name": "some-network-name",
                },
            },
        }

        result = Ns._process_net_params(
            target_vld=target_vld,
            indata=indata,
            vim_info=vim_info,
            target_record_id=target_record_id,
        )

        self.assertDictEqual(expected_result, result)

    def test__process_net_params_with_vim_network_id(
        self,
    ):
        target_vld = {
            "name": "vld-name",
        }
        indata = {
            "name": "ns-name",
        }
        vim_info = {
            "vim_network_id": "some-network-id",
        }
        target_record_id = "vld.sdn.something"
        expected_result = {
            "find_params": {
                "filter_dict": {
                    "id": "some-network-id",
                },
            },
        }

        result = Ns._process_net_params(
            target_vld=target_vld,
            indata=indata,
            vim_info=vim_info,
            target_record_id=target_record_id,
        )

        self.assertDictEqual(expected_result, result)

    def test__process_net_params_with_mgmt_network(
        self,
    ):
        target_vld = {
            "id": "vld-id",
            "name": "vld-name",
            "mgmt-network": "some-mgmt-network",
        }
        indata = {
            "name": "ns-name",
        }
        vim_info = {}
        target_record_id = "vld.sdn.something"
        expected_result = {
            "find_params": {
                "mgmt": True,
                "name": "vld-id",
            },
        }

        result = Ns._process_net_params(
            target_vld=target_vld,
            indata=indata,
            vim_info=vim_info,
            target_record_id=target_record_id,
        )

        self.assertDictEqual(expected_result, result)

    def test__process_net_params_with_underlay_eline(
        self,
    ):
        target_vld = {
            "name": "vld-name",
            "underlay": "some-underlay-here",
            "type": "ELINE",
        }
        indata = {
            "name": "ns-name",
        }
        vim_info = {
            "provider_network": "some-profile-here",
            "ip_profile": {
                "some_ip_profile": "here",
            },
        }
        target_record_id = ""
        expected_result = {
            "params": {
                "ip_profile": {
                    "some_ip_profile": "here",
                },
                "net_name": "ns-name-vld-name",
                "net_type": "ptp",
                "provider_network_profile": "some-profile-here",
            }
        }

        result = Ns._process_net_params(
            target_vld=target_vld,
            indata=indata,
            vim_info=vim_info,
            target_record_id=target_record_id,
        )

        self.assertDictEqual(expected_result, result)

    def test__process_net_params_with_underlay_elan(
        self,
    ):
        target_vld = {
            "name": "vld-name",
            "underlay": "some-underlay-here",
            "type": "ELAN",
        }
        indata = {
            "name": "ns-name",
        }
        vim_info = {
            "provider_network": "some-profile-here",
            "ip_profile": {
                "some_ip_profile": "here",
            },
        }
        target_record_id = ""
        expected_result = {
            "params": {
                "ip_profile": {
                    "some_ip_profile": "here",
                },
                "net_name": "ns-name-vld-name",
                "net_type": "data",
                "provider_network_profile": "some-profile-here",
            }
        }

        result = Ns._process_net_params(
            target_vld=target_vld,
            indata=indata,
            vim_info=vim_info,
            target_record_id=target_record_id,
        )

        self.assertDictEqual(expected_result, result)

    def test__get_cloud_init_exception(self):
        db_mock = MagicMock(name="database mock")
        fs_mock = None

        location = ""

        with self.assertRaises(NsException):
            Ns._get_cloud_init(db=db_mock, fs=fs_mock, location=location)

    def test__get_cloud_init_file_fs_exception(self):
        db_mock = MagicMock(name="database mock")
        fs_mock = None

        location = "vnfr_id_123456:file:test_file"
        db_mock.get_one.return_value = {
            "_admin": {
                "storage": {
                    "folder": "/home/osm",
                    "pkg-dir": "vnfr_test_dir",
                },
            },
        }

        with self.assertRaises(NsException):
            Ns._get_cloud_init(db=db_mock, fs=fs_mock, location=location)

    def test__get_cloud_init_file(self):
        db_mock = MagicMock(name="database mock")
        fs_mock = MagicMock(name="filesystem mock")
        file_mock = MagicMock(name="file mock")

        location = "vnfr_id_123456:file:test_file"
        cloud_init_content = "this is a cloud init file content"

        db_mock.get_one.return_value = {
            "_admin": {
                "storage": {
                    "folder": "/home/osm",
                    "pkg-dir": "vnfr_test_dir",
                },
            },
        }
        fs_mock.file_open.return_value = file_mock
        file_mock.__enter__.return_value.read.return_value = cloud_init_content

        result = Ns._get_cloud_init(db=db_mock, fs=fs_mock, location=location)

        self.assertEqual(cloud_init_content, result)

    def test__get_cloud_init_vdu(self):
        db_mock = MagicMock(name="database mock")
        fs_mock = None

        location = "vnfr_id_123456:vdu:0"
        cloud_init_content = "this is a cloud init file content"

        db_mock.get_one.return_value = {
            "vdu": {
                0: {
                    "cloud-init": cloud_init_content,
                },
            },
        }

        result = Ns._get_cloud_init(db=db_mock, fs=fs_mock, location=location)

        self.assertEqual(cloud_init_content, result)

    @patch("jinja2.Environment.__init__")
    def test__parse_jinja2_undefined_error(self, env_mock: Mock):
        cloud_init_content = None
        params = None
        context = None

        env_mock.side_effect = UndefinedError("UndefinedError occurred.")

        with self.assertRaises(NsException):
            Ns._parse_jinja2(
                cloud_init_content=cloud_init_content, params=params, context=context
            )

    @patch("jinja2.Environment.__init__")
    def test__parse_jinja2_template_error(self, env_mock: Mock):
        cloud_init_content = None
        params = None
        context = None

        env_mock.side_effect = TemplateError("TemplateError occurred.")

        with self.assertRaises(NsException):
            Ns._parse_jinja2(
                cloud_init_content=cloud_init_content, params=params, context=context
            )

    @patch("jinja2.Environment.__init__")
    def test__parse_jinja2_template_not_found(self, env_mock: Mock):
        cloud_init_content = None
        params = None
        context = None

        env_mock.side_effect = TemplateNotFound("TemplateNotFound occurred.")

        with self.assertRaises(NsException):
            Ns._parse_jinja2(
                cloud_init_content=cloud_init_content, params=params, context=context
            )

    def test_rendering_jinja2_temp_without_special_characters(self):
        cloud_init_content = """
        disk_setup:
            ephemeral0:
                table_type: {{type}}
                layout: True
                overwrite: {{is_override}}
        runcmd:
             - [ ls, -l, / ]
             - [ sh, -xc, "echo $(date) '{{command}}'" ]
        """
        params = {
            "type": "mbr",
            "is_override": "False",
            "command": "; mkdir abc",
        }
        context = "cloud-init for VM"
        expected_result = """
        disk_setup:
            ephemeral0:
                table_type: mbr
                layout: True
                overwrite: False
        runcmd:
             - [ ls, -l, / ]
             - [ sh, -xc, "echo $(date) '; mkdir abc'" ]
        """
        result = Ns._parse_jinja2(
            cloud_init_content=cloud_init_content, params=params, context=context
        )
        self.assertEqual(result, expected_result)

    def test_rendering_jinja2_temp_with_special_characters(self):
        cloud_init_content = """
        disk_setup:
            ephemeral0:
                table_type: {{type}}
                layout: True
                overwrite: {{is_override}}
        runcmd:
             - [ ls, -l, / ]
             - [ sh, -xc, "echo $(date) '{{command}}'" ]
        """
        params = {
            "type": "mbr",
            "is_override": "False",
            "command": "& rm -rf",
        }
        context = "cloud-init for VM"
        expected_result = """
        disk_setup:
            ephemeral0:
                table_type: mbr
                layout: True
                overwrite: False
        runcmd:
             - [ ls, -l, / ]
             - [ sh, -xc, "echo $(date) '& rm -rf /'" ]
        """
        result = Ns._parse_jinja2(
            cloud_init_content=cloud_init_content, params=params, context=context
        )
        self.assertNotEqual(result, expected_result)

    def test_rendering_jinja2_temp_with_special_characters_autoescape_is_false(self):
        with patch("osm_ng_ro.ns.Environment") as mock_environment:
            mock_environment.return_value = Environment(
                undefined=StrictUndefined,
                autoescape=select_autoescape(default_for_string=False, default=False),
            )
            cloud_init_content = """
                disk_setup:
                    ephemeral0:
                        table_type: {{type}}
                        layout: True
                        overwrite: {{is_override}}
                runcmd:
                     - [ ls, -l, / ]
                     - [ sh, -xc, "echo $(date) '{{command}}'" ]
                """
            params = {
                "type": "mbr",
                "is_override": "False",
                "command": "& rm -rf /",
            }
            context = "cloud-init for VM"
            expected_result = """
                disk_setup:
                    ephemeral0:
                        table_type: mbr
                        layout: True
                        overwrite: False
                runcmd:
                     - [ ls, -l, / ]
                     - [ sh, -xc, "echo $(date) '& rm -rf /'" ]
                """
            result = Ns._parse_jinja2(
                cloud_init_content=cloud_init_content,
                params=params,
                context=context,
            )
            self.assertEqual(result, expected_result)

    @patch("osm_ng_ro.ns.Ns._assign_vim")
    def test__rebuild_start_stop_task__successful(self, assign_vim):
        self.ns = Ns()
        extra_dict = {}
        actions = ["start", "stop", "rebuild"]
        vdu_index = "0"
        task_index = 0
        for action in actions:
            params = {
                "vim_vm_id": "f37b18ef-3caa-4dc9-ab91-15c669b16396",
                "action": action,
            }
            extra_dict["params"] = params
            expected_result = deepcopy(expected_result_rebuild_start_stop)
            expected_result["target_record"] = (
                "vnfrs:665b4165-ce24-4320-bf19-b9a45bade49f:vdur.0.vim_info.vim:f9f370ac-0d44-41a7-9000-457f2332bc35"
            )
            expected_result["params"] = params
            task = self.ns.rebuild_start_stop_task(
                vdu_id,
                vnf_id,
                vdu_index,
                action_id,
                nsr_id_2,
                task_index,
                target_vim,
                extra_dict,
            )
            self.assertDictEqual(task, expected_result)

    @patch("osm_ng_ro.ns.Ns._assign_vim")
    def test__rebuild_start_stop_task__empty_extra_dict__task_without_params(
        self, assign_vim
    ):
        self.ns = Ns()
        extra_dict = {}
        actions = ["start", "stop", "rebuild"]
        vdu_index = "0"
        task_index = 0
        expected_result = deepcopy(expected_result_rebuild_start_stop)
        expected_result["target_record"] = (
            "vnfrs:665b4165-ce24-4320-bf19-b9a45bade49f:vdur.0.vim_info.vim:f9f370ac-0d44-41a7-9000-457f2332bc35"
        )
        for _ in actions:
            task = self.ns.rebuild_start_stop_task(
                vdu_id,
                vnf_id,
                vdu_index,
                action_id,
                nsr_id_2,
                task_index,
                target_vim,
                extra_dict,
            )
            self.assertDictEqual(task, expected_result)

    @patch("osm_ng_ro.ns.Ns._assign_vim")
    def test__rebuild_start_stop_task__different_vdu_index__target_record_changes(
        self, assign_vim
    ):
        self.ns = Ns()
        extra_dict = {}
        actions = ["start", "stop", "rebuild"]
        vdu_index = "4"
        task_index = 0
        for action in actions:
            params = {
                "vim_vm_id": "f37b18ef-3caa-4dc9-ab91-15c669b16396",
                "action": action,
            }
            extra_dict["params"] = params
            expected_result = deepcopy(expected_result_rebuild_start_stop)
            expected_result["target_record"] = (
                "vnfrs:665b4165-ce24-4320-bf19-b9a45bade49f:vdur.4.vim_info.vim:f9f370ac-0d44-41a7-9000-457f2332bc35"
            )
            expected_result["params"] = params
            task = self.ns.rebuild_start_stop_task(
                vdu_id,
                vnf_id,
                vdu_index,
                action_id,
                nsr_id_2,
                task_index,
                target_vim,
                extra_dict,
            )
            self.assertDictEqual(task, expected_result)

    @patch("osm_ng_ro.ns.Ns._assign_vim")
    def test__rebuild_start_stop_task__different_task_index__task_id_changes(
        self, assign_vim
    ):
        self.ns = Ns()
        extra_dict = {}
        actions = ["start", "stop", "rebuild"]
        vdu_index = "0"
        task_index = 3
        for action in actions:
            params = {
                "vim_vm_id": "f37b18ef-3caa-4dc9-ab91-15c669b16396",
                "action": action,
            }
            extra_dict["params"] = params
            expected_result = deepcopy(expected_result_rebuild_start_stop)
            expected_result["target_record"] = (
                "vnfrs:665b4165-ce24-4320-bf19-b9a45bade49f:vdur.0.vim_info.vim:f9f370ac-0d44-41a7-9000-457f2332bc35"
            )
            expected_result["params"] = params
            expected_result["task_id"] = "bb937f49-3870-4169-b758-9732e1ff40f3:3"
            task = self.ns.rebuild_start_stop_task(
                vdu_id,
                vnf_id,
                vdu_index,
                action_id,
                nsr_id_2,
                task_index,
                target_vim,
                extra_dict,
            )
            self.assertDictEqual(task, expected_result)

    @patch("osm_ng_ro.ns.Ns._assign_vim")
    def test__rebuild_start_stop_task__assign_vim_raises__task_is_not_created(
        self, assign_vim
    ):
        self.ns = Ns()
        extra_dict = {}
        actions = ["start", "stop", "rebuild"]
        vdu_index = "0"
        task_index = 0
        for action in actions:
            params = {
                "vim_vm_id": "f37b18ef-3caa-4dc9-ab91-15c669b16396",
                "action": action,
            }
            extra_dict["params"] = params
            assign_vim.side_effect = TestException("Can not connect to VIM.")
            with self.assertRaises(TestException) as err:
                task = self.ns.rebuild_start_stop_task(
                    vdu_id,
                    vnf_id,
                    vdu_index,
                    action_id,
                    nsr_id_2,
                    task_index,
                    target_vim,
                    extra_dict,
                )
                self.assertEqual(task, None)
                self.assertEqual(str(err.exception), "Can not connect to VIM.")

    @patch("osm_ng_ro.ns.Ns._assign_vim")
    def test_verticalscale_task__successful(self, assign_vim):
        self.ns = Ns()
        vdu_index = "1"
        task_index = 1
        task = self.ns.verticalscale_task(
            vdu,
            vnf,
            vdu_index,
            action_id,
            nsr_id_2,
            task_index,
            extra_dict_vertical_scale,
        )
        self.assertDictEqual(task, expected_result_vertical_scale)

    @patch("osm_ng_ro.ns.Ns._assign_vim")
    def test_verticalscale_task__task_index_changes__task_id_changes(self, assign_vim):
        self.ns = Ns()
        vdu_index = "1"
        task_index = 2
        expected_result = deepcopy(expected_result_vertical_scale)
        expected_result["task_id"] = "bb937f49-3870-4169-b758-9732e1ff40f3:2"
        task = self.ns.verticalscale_task(
            vdu,
            vnf,
            vdu_index,
            action_id,
            nsr_id_2,
            task_index,
            extra_dict_vertical_scale,
        )
        self.assertDictEqual(task, expected_result)

    @patch("osm_ng_ro.ns.Ns._assign_vim")
    def test_verticalscale_task__empty_extra_dict__expected_result_without_params(
        self, assign_vim
    ):
        self.ns = Ns()
        extra_dict = {"params": {}}
        vdu_index = "1"
        task_index = 1
        expected_result = {
            "target_id": "vim:f9f370ac-0d44-41a7-9000-457f2332bc35",
            "action_id": "bb937f49-3870-4169-b758-9732e1ff40f3",
            "nsr_id": "993166fe-723e-4680-ac4b-b1af2541ae31",
            "task_id": "bb937f49-3870-4169-b758-9732e1ff40f3:1",
            "status": "SCHEDULED",
            "action": "EXEC",
            "item": "verticalscale",
            "target_record": "vnfrs:665b4165-ce24-4320-bf19-b9a45bade49f:vdur.1.vim_info.vim:f9f370ac-0d44-41a7-9000-457f2332bc35",
            "target_record_id": "vnfrs:665b4165-ce24-4320-bf19-b9a45bade49f:vdur.bb9c43f9-10a2-4569-a8a8-957c3528b6d1",
            "params": {
                "flavor_id": "TASK-nsrs:993166fe-723e-4680-ac4b-b1af2541ae31:flavor.0"
            },
            "depends_on": ["nsrs:993166fe-723e-4680-ac4b-b1af2541ae31:flavor.0"],
        }

        task = self.ns.verticalscale_task(
            vdu, vnf, vdu_index, action_id, nsr_id_2, task_index, extra_dict
        )
        self.assertDictEqual(task, expected_result)

    @patch("osm_ng_ro.ns.Ns._assign_vim")
    def test_verticalscale_task__assign_vim_raises__task_is_not_created(
        self, assign_vim
    ):
        self.ns = Ns()
        vdu_index = "1"
        task_index = 1
        assign_vim.side_effect = TestException("Can not connect to VIM.")
        with self.assertRaises(TestException) as err:
            task = self.ns.verticalscale_task(
                vdu,
                vnf,
                vdu_index,
                action_id,
                nsr_id_2,
                task_index,
                extra_dict_vertical_scale,
            )
            self.assertEqual(task, {})
            self.assertEqual(str(err.exception), "Can not connect to VIM.")

    @patch("osm_ng_ro.ns.Ns._assign_vim")
    def test_migrate_task__successful(self, assign_vim):
        self.ns = Ns()
        vdu_index = "1"
        task_index = 1
        task = self.ns.migrate_task(
            vdu, vnf, vdu_index, action_id, nsr_id_2, task_index, extra_dict_migrate
        )
        self.assertDictEqual(task, expected_result_migrate)

    @patch("osm_ng_ro.ns.Ns._assign_vim")
    def test_migrate_task__empty_extra_dict__task_without_params(self, assign_vim):
        self.ns = Ns()
        extra_dict = {}
        vdu_index = "1"
        task_index = 1
        expected_result = deepcopy(expected_result_migrate)
        expected_result.pop("params")
        task = self.ns.migrate_task(
            vdu, vnf, vdu_index, action_id, nsr_id_2, task_index, extra_dict
        )
        self.assertDictEqual(task, expected_result)

    @patch("osm_ng_ro.ns.Ns._assign_vim")
    def test_migrate_task__different_vdu_index__target_record_with_different_vdu_index(
        self, assign_vim
    ):
        self.ns = Ns()
        vdu_index = "4"
        task_index = 1
        expected_result = deepcopy(expected_result_migrate)
        expected_result["target_record"] = (
            "vnfrs:665b4165-ce24-4320-bf19-b9a45bade49f:vdur.4.vim_info.vim:f9f370ac-0d44-41a7-9000-457f2332bc35"
        )
        task = self.ns.migrate_task(
            vdu, vnf, vdu_index, action_id, nsr_id_2, task_index, extra_dict_migrate
        )
        self.assertDictEqual(task, expected_result)

    @patch("osm_ng_ro.ns.Ns._assign_vim")
    def test_migrate_task__assign_vim_raises__task_is_not_created(self, assign_vim):
        self.ns = Ns()
        vdu_index = "1"
        task_index = 1
        assign_vim.side_effect = TestException("Can not connect to VIM.")
        with self.assertRaises(TestException) as err:
            task = self.ns.migrate_task(
                vdu, vnf, vdu_index, action_id, nsr_id, task_index, extra_dict_migrate
            )
            self.assertDictEqual(task, {})
            self.assertEqual(str(err.exception), "Can not connect to VIM.")


class TestProcessVduParams(unittest.TestCase):
    def setUp(self):
        self.ns = Ns()
        self.logger = CopyingMock(autospec=True)

    @patch("osm_ng_ro.ns.Ns.is_volume_keeping_required")
    def test_find_persistent_root_volumes_empty_instantiation_vol_list(
        self, mock_volume_keeping_required
    ):
        """Find persistent root volume, instantiation_vol_list is empty."""
        vnfd = deepcopy(vnfd_wth_persistent_storage)
        target_vdu = target_vdu_wth_persistent_storage
        vdu_instantiation_volumes_list = []
        disk_list = []
        mock_volume_keeping_required.return_value = True
        expected_root_disk = {
            "id": "persistent-root-volume",
            "type-of-storage": "persistent-storage:persistent-storage",
            "size-of-storage": "10",
            "vdu-storage-requirements": [{"key": "keep-volume", "value": "true"}],
        }
        expected_persist_root_disk = {
            "persistent-root-volume": {
                "image_id": "ubuntu20.04",
                "size": "10",
                "keep": True,
            }
        }
        expected_disk_list = [
            {
                "image_id": "ubuntu20.04",
                "size": "10",
                "keep": True,
            },
        ]
        persist_root_disk = self.ns.find_persistent_root_volumes(
            vnfd, target_vdu, vdu_instantiation_volumes_list, disk_list
        )
        self.assertEqual(persist_root_disk, expected_persist_root_disk)
        mock_volume_keeping_required.assert_called_once_with(expected_root_disk)
        self.assertEqual(disk_list, expected_disk_list)
        self.assertEqual(len(disk_list), 1)

    @patch("osm_ng_ro.ns.Ns.is_volume_keeping_required")
    def test_find_persistent_root_volumes_always_selects_first_vsd_as_root(
        self, mock_volume_keeping_required
    ):
        """Find persistent root volume, always selects the first vsd as root volume."""
        vnfd = deepcopy(vnfd_wth_persistent_storage)
        vnfd["vdu"][0]["virtual-storage-desc"] = [
            "persistent-volume2",
            "persistent-root-volume",
            "ephemeral-volume",
        ]
        target_vdu = target_vdu_wth_persistent_storage
        vdu_instantiation_volumes_list = []
        disk_list = []
        mock_volume_keeping_required.return_value = True
        expected_root_disk = {
            "id": "persistent-volume2",
            "type-of-storage": "persistent-storage:persistent-storage",
            "size-of-storage": "10",
        }
        expected_persist_root_disk = {
            "persistent-volume2": {
                "image_id": "ubuntu20.04",
                "size": "10",
                "keep": True,
            }
        }
        expected_disk_list = [
            {
                "image_id": "ubuntu20.04",
                "size": "10",
                "keep": True,
            },
        ]
        persist_root_disk = self.ns.find_persistent_root_volumes(
            vnfd, target_vdu, vdu_instantiation_volumes_list, disk_list
        )
        self.assertEqual(persist_root_disk, expected_persist_root_disk)
        mock_volume_keeping_required.assert_called_once_with(expected_root_disk)
        self.assertEqual(disk_list, expected_disk_list)
        self.assertEqual(len(disk_list), 1)

    @patch("osm_ng_ro.ns.Ns.is_volume_keeping_required")
    def test_find_persistent_root_volumes_empty_size_of_storage(
        self, mock_volume_keeping_required
    ):
        """Find persistent root volume, size of storage is empty."""
        vnfd = deepcopy(vnfd_wth_persistent_storage)
        vnfd["virtual-storage-desc"][0]["size-of-storage"] = ""
        vnfd["vdu"][0]["virtual-storage-desc"] = [
            "persistent-volume2",
            "persistent-root-volume",
            "ephemeral-volume",
        ]
        target_vdu = target_vdu_wth_persistent_storage
        vdu_instantiation_volumes_list = []
        disk_list = []
        persist_root_disk = self.ns.find_persistent_root_volumes(
            vnfd, target_vdu, vdu_instantiation_volumes_list, disk_list
        )
        self.assertEqual(persist_root_disk, {})
        mock_volume_keeping_required.assert_not_called()
        self.assertEqual(disk_list, [])

    @patch("osm_ng_ro.ns.Ns.is_volume_keeping_required")
    def test_find_persistent_root_volumes_keeping_is_not_required(
        self, mock_volume_keeping_required
    ):
        """Find persistent root volume, volume keeping is not required."""
        vnfd = deepcopy(vnfd_wth_persistent_storage)
        vnfd["virtual-storage-desc"][1]["vdu-storage-requirements"] = [
            {"key": "keep-volume", "value": "false"},
        ]
        target_vdu = target_vdu_wth_persistent_storage
        vdu_instantiation_volumes_list = []
        disk_list = []
        mock_volume_keeping_required.return_value = False
        expected_root_disk = {
            "id": "persistent-root-volume",
            "type-of-storage": "persistent-storage:persistent-storage",
            "size-of-storage": "10",
            "vdu-storage-requirements": [{"key": "keep-volume", "value": "false"}],
        }
        expected_persist_root_disk = {
            "persistent-root-volume": {
                "image_id": "ubuntu20.04",
                "size": "10",
                "keep": False,
            }
        }
        expected_disk_list = [
            {
                "image_id": "ubuntu20.04",
                "size": "10",
                "keep": False,
            },
        ]
        persist_root_disk = self.ns.find_persistent_root_volumes(
            vnfd, target_vdu, vdu_instantiation_volumes_list, disk_list
        )
        self.assertEqual(persist_root_disk, expected_persist_root_disk)
        mock_volume_keeping_required.assert_called_once_with(expected_root_disk)
        self.assertEqual(disk_list, expected_disk_list)
        self.assertEqual(len(disk_list), 1)

    @patch("osm_ng_ro.ns.Ns.is_volume_keeping_required")
    def test_find_persistent_root_volumes_target_vdu_mismatch(
        self, mock_volume_keeping_required
    ):
        """Find persistent root volume, target vdu name is not matching."""
        vnfd = deepcopy(vnfd_wth_persistent_storage)
        vnfd["vdu"][0]["name"] = "Several_Volumes-VM"
        target_vdu = target_vdu_wth_persistent_storage
        vdu_instantiation_volumes_list = []
        disk_list = []
        result = self.ns.find_persistent_root_volumes(
            vnfd, target_vdu, vdu_instantiation_volumes_list, disk_list
        )
        self.assertEqual(result, None)
        mock_volume_keeping_required.assert_not_called()
        self.assertEqual(disk_list, [])
        self.assertEqual(len(disk_list), 0)

    @patch("osm_ng_ro.ns.Ns.is_volume_keeping_required")
    def test_find_persistent_root_volumes_with_instantiation_vol_list(
        self, mock_volume_keeping_required
    ):
        """Find persistent root volume, existing volume needs to be used."""
        vnfd = deepcopy(vnfd_wth_persistent_storage)
        target_vdu = target_vdu_wth_persistent_storage
        vdu_instantiation_volumes_list = [
            {
                "vim-volume-id": vim_volume_id,
                "name": "persistent-root-volume",
            }
        ]
        disk_list = []
        expected_persist_root_disk = {
            "persistent-root-volume": {
                "vim_volume_id": vim_volume_id,
                "image_id": "ubuntu20.04",
            },
        }
        expected_disk_list = [
            {
                "vim_volume_id": vim_volume_id,
                "image_id": "ubuntu20.04",
            },
        ]
        persist_root_disk = self.ns.find_persistent_root_volumes(
            vnfd, target_vdu, vdu_instantiation_volumes_list, disk_list
        )
        self.assertEqual(persist_root_disk, expected_persist_root_disk)
        mock_volume_keeping_required.assert_not_called()
        self.assertEqual(disk_list, expected_disk_list)
        self.assertEqual(len(disk_list), 1)

    @patch("osm_ng_ro.ns.Ns.is_volume_keeping_required")
    def test_find_persistent_root_volumes_invalid_instantiation_params(
        self, mock_volume_keeping_required
    ):
        """Find persistent root volume, existing volume id keyword is invalid."""
        vnfd = deepcopy(vnfd_wth_persistent_storage)
        target_vdu = target_vdu_wth_persistent_storage
        vdu_instantiation_volumes_list = [
            {
                "volume-id": vim_volume_id,
                "name": "persistent-root-volume",
            }
        ]
        disk_list = []
        with self.assertRaises(KeyError):
            self.ns.find_persistent_root_volumes(
                vnfd, target_vdu, vdu_instantiation_volumes_list, disk_list
            )
        mock_volume_keeping_required.assert_not_called()
        self.assertEqual(disk_list, [])
        self.assertEqual(len(disk_list), 0)

    @patch("osm_ng_ro.ns.Ns.is_volume_keeping_required")
    def test_find_persistent_volumes_vdu_wth_persistent_root_disk_wthout_inst_vol_list(
        self, mock_volume_keeping_required
    ):
        """Find persistent ordinary volume, there is persistent root disk and instatiation volume list is empty."""
        persistent_root_disk = {
            "persistent-root-volume": {
                "image_id": "ubuntu20.04",
                "size": "10",
                "keep": False,
            }
        }
        mock_volume_keeping_required.return_value = False
        target_vdu = target_vdu_wth_persistent_storage
        vdu_instantiation_volumes_list = []
        disk_list = [
            {
                "image_id": "ubuntu20.04",
                "size": "10",
                "keep": False,
            },
        ]
        expected_disk = {
            "id": "persistent-volume2",
            "size-of-storage": "10",
            "type-of-storage": "persistent-storage:persistent-storage",
        }
        expected_disk_list = [
            {
                "image_id": "ubuntu20.04",
                "size": "10",
                "keep": False,
            },
            {
                "size": "10",
                "keep": False,
            },
        ]
        self.ns.find_persistent_volumes(
            persistent_root_disk, target_vdu, vdu_instantiation_volumes_list, disk_list
        )
        self.assertEqual(disk_list, expected_disk_list)
        mock_volume_keeping_required.assert_called_once_with(expected_disk)

    @patch("osm_ng_ro.ns.Ns.is_volume_keeping_required")
    def test_find_persistent_volumes_vdu_wth_inst_vol_list(
        self, mock_volume_keeping_required
    ):
        """Find persistent ordinary volume, vim-volume-id is given as instantiation parameter."""
        persistent_root_disk = {
            "persistent-root-volume": {
                "image_id": "ubuntu20.04",
                "size": "10",
                "keep": False,
            }
        }
        vdu_instantiation_volumes_list = [
            {
                "vim-volume-id": vim_volume_id,
                "name": "persistent-volume2",
            }
        ]
        target_vdu = target_vdu_wth_persistent_storage
        disk_list = [
            {
                "image_id": "ubuntu20.04",
                "size": "10",
                "keep": False,
            },
        ]
        expected_disk_list = [
            {
                "image_id": "ubuntu20.04",
                "size": "10",
                "keep": False,
            },
            {
                "vim_volume_id": vim_volume_id,
            },
        ]
        self.ns.find_persistent_volumes(
            persistent_root_disk, target_vdu, vdu_instantiation_volumes_list, disk_list
        )
        self.assertEqual(disk_list, expected_disk_list)
        mock_volume_keeping_required.assert_not_called()

    @patch("osm_ng_ro.ns.Ns.is_volume_keeping_required")
    def test_find_persistent_volumes_vdu_wthout_persistent_storage(
        self, mock_volume_keeping_required
    ):
        """Find persistent ordinary volume, there is not any persistent disk."""
        persistent_root_disk = {}
        vdu_instantiation_volumes_list = []
        mock_volume_keeping_required.return_value = False
        target_vdu = target_vdu_wthout_persistent_storage
        disk_list = []
        self.ns.find_persistent_volumes(
            persistent_root_disk, target_vdu, vdu_instantiation_volumes_list, disk_list
        )
        self.assertEqual(disk_list, disk_list)
        mock_volume_keeping_required.assert_not_called()

    @patch("osm_ng_ro.ns.Ns.is_volume_keeping_required")
    def test_find_persistent_volumes_vdu_wth_persistent_root_disk_wthout_ordinary_disk(
        self, mock_volume_keeping_required
    ):
        """There is persistent root disk, but there is not ordinary persistent disk."""
        persistent_root_disk = {
            "persistent-root-volume": {
                "image_id": "ubuntu20.04",
                "size": "10",
                "keep": False,
            }
        }
        vdu_instantiation_volumes_list = []
        mock_volume_keeping_required.return_value = False
        target_vdu = deepcopy(target_vdu_wth_persistent_storage)
        target_vdu["virtual-storages"] = [
            {
                "id": "persistent-root-volume",
                "size-of-storage": "10",
                "type-of-storage": "persistent-storage:persistent-storage",
                "vdu-storage-requirements": [
                    {"key": "keep-volume", "value": "true"},
                ],
            },
            {
                "id": "ephemeral-volume",
                "size-of-storage": "1",
                "type-of-storage": "etsi-nfv-descriptors:ephemeral-storage",
            },
        ]
        disk_list = [
            {
                "image_id": "ubuntu20.04",
                "size": "10",
                "keep": False,
            },
        ]
        self.ns.find_persistent_volumes(
            persistent_root_disk, target_vdu, vdu_instantiation_volumes_list, disk_list
        )
        self.assertEqual(disk_list, disk_list)
        mock_volume_keeping_required.assert_not_called()

    @patch("osm_ng_ro.ns.Ns.is_volume_keeping_required")
    def test_find_persistent_volumes_wth_inst_vol_list_disk_id_mismatch(
        self, mock_volume_keeping_required
    ):
        """Find persistent ordinary volume, volume id is not persistent_root_disk dict,
        vim-volume-id is given as instantiation parameter but disk id is not matching.
        """
        mock_volume_keeping_required.return_value = True
        vdu_instantiation_volumes_list = [
            {
                "vim-volume-id": vim_volume_id,
                "name": "persistent-volume3",
            }
        ]
        persistent_root_disk = {
            "persistent-root-volume": {
                "image_id": "ubuntu20.04",
                "size": "10",
                "keep": False,
            }
        }
        disk_list = [
            {
                "image_id": "ubuntu20.04",
                "size": "10",
                "keep": False,
            },
        ]
        expected_disk_list = [
            {
                "image_id": "ubuntu20.04",
                "size": "10",
                "keep": False,
            },
            {
                "size": "10",
                "keep": True,
            },
        ]
        expected_disk = {
            "id": "persistent-volume2",
            "size-of-storage": "10",
            "type-of-storage": "persistent-storage:persistent-storage",
        }
        target_vdu = target_vdu_wth_persistent_storage
        self.ns.find_persistent_volumes(
            persistent_root_disk, target_vdu, vdu_instantiation_volumes_list, disk_list
        )
        self.assertEqual(disk_list, expected_disk_list)
        mock_volume_keeping_required.assert_called_once_with(expected_disk)

    def test_is_volume_keeping_required_true(self):
        """Volume keeping is required."""
        virtual_storage_descriptor = {
            "id": "persistent-root-volume",
            "type-of-storage": "persistent-storage:persistent-storage",
            "size-of-storage": "10",
            "vdu-storage-requirements": [
                {"key": "keep-volume", "value": "true"},
            ],
        }
        result = self.ns.is_volume_keeping_required(virtual_storage_descriptor)
        self.assertEqual(result, True)

    def test_is_volume_keeping_required_false(self):
        """Volume keeping is not required."""
        virtual_storage_descriptor = {
            "id": "persistent-root-volume",
            "type-of-storage": "persistent-storage:persistent-storage",
            "size-of-storage": "10",
            "vdu-storage-requirements": [
                {"key": "keep-volume", "value": "false"},
            ],
        }
        result = self.ns.is_volume_keeping_required(virtual_storage_descriptor)
        self.assertEqual(result, False)

    def test_is_volume_keeping_required_wthout_vdu_storage_reqirement(self):
        """Volume keeping is not required, vdu-storage-requirements key does not exist."""
        virtual_storage_descriptor = {
            "id": "persistent-root-volume",
            "type-of-storage": "persistent-storage:persistent-storage",
            "size-of-storage": "10",
        }
        result = self.ns.is_volume_keeping_required(virtual_storage_descriptor)
        self.assertEqual(result, False)

    def test_is_volume_keeping_required_wrong_keyword(self):
        """vdu-storage-requirements key to indicate keeping-volume is wrong."""
        virtual_storage_descriptor = {
            "id": "persistent-root-volume",
            "type-of-storage": "persistent-storage:persistent-storage",
            "size-of-storage": "10",
            "vdu-storage-requirements": [
                {"key": "hold-volume", "value": "true"},
            ],
        }
        result = self.ns.is_volume_keeping_required(virtual_storage_descriptor)
        self.assertEqual(result, False)

    def test_sort_vdu_interfaces_position_all_wth_positions(self):
        """Interfaces are sorted according to position, all have positions."""
        target_vdu = deepcopy(target_vdu_wth_persistent_storage)
        target_vdu["interfaces"] = [
            {
                "name": "vdu-eth1",
                "ns-vld-id": "datanet",
                "position": 2,
            },
            {
                "name": "vdu-eth0",
                "ns-vld-id": "mgmtnet",
                "position": 1,
            },
        ]
        sorted_interfaces = [
            {
                "name": "vdu-eth0",
                "ns-vld-id": "mgmtnet",
                "position": 1,
            },
            {
                "name": "vdu-eth1",
                "ns-vld-id": "datanet",
                "position": 2,
            },
        ]
        self.ns._sort_vdu_interfaces(target_vdu)
        self.assertEqual(target_vdu["interfaces"], sorted_interfaces)

    def test_sort_vdu_interfaces_position_some_wth_position(self):
        """Interfaces are sorted according to position, some of them have positions."""
        target_vdu = deepcopy(target_vdu_wth_persistent_storage)
        target_vdu["interfaces"] = [
            {
                "name": "vdu-eth0",
                "ns-vld-id": "mgmtnet",
            },
            {
                "name": "vdu-eth1",
                "ns-vld-id": "datanet",
                "position": 1,
            },
        ]
        sorted_interfaces = [
            {
                "name": "vdu-eth1",
                "ns-vld-id": "datanet",
                "position": 1,
            },
            {
                "name": "vdu-eth0",
                "ns-vld-id": "mgmtnet",
            },
        ]
        self.ns._sort_vdu_interfaces(target_vdu)
        self.assertEqual(target_vdu["interfaces"], sorted_interfaces)

    def test_sort_vdu_interfaces_position_empty_interface_list(self):
        """Interface list is empty."""
        target_vdu = deepcopy(target_vdu_wth_persistent_storage)
        target_vdu["interfaces"] = []
        sorted_interfaces = []
        self.ns._sort_vdu_interfaces(target_vdu)
        self.assertEqual(target_vdu["interfaces"], sorted_interfaces)

    def test_partially_locate_vdu_interfaces(self):
        """Some interfaces have positions."""
        target_vdu = deepcopy(target_vdu_wth_persistent_storage)
        target_vdu["interfaces"] = [
            {
                "name": "vdu-eth1",
                "ns-vld-id": "net1",
            },
            {"name": "vdu-eth2", "ns-vld-id": "net2", "position": 3},
            {
                "name": "vdu-eth3",
                "ns-vld-id": "mgmtnet",
            },
            {
                "name": "vdu-eth1",
                "ns-vld-id": "datanet",
                "position": 1,
            },
        ]
        self.ns._partially_locate_vdu_interfaces(target_vdu)
        self.assertDictEqual(
            target_vdu["interfaces"][0],
            {
                "name": "vdu-eth1",
                "ns-vld-id": "datanet",
                "position": 1,
            },
        )
        self.assertDictEqual(
            target_vdu["interfaces"][2],
            {"name": "vdu-eth2", "ns-vld-id": "net2", "position": 3},
        )

    def test_partially_locate_vdu_interfaces_position_start_from_0(self):
        """Some interfaces have positions, position start from 0."""
        target_vdu = deepcopy(target_vdu_wth_persistent_storage)
        target_vdu["interfaces"] = [
            {
                "name": "vdu-eth1",
                "ns-vld-id": "net1",
            },
            {"name": "vdu-eth2", "ns-vld-id": "net2", "position": 3},
            {
                "name": "vdu-eth3",
                "ns-vld-id": "mgmtnet",
            },
            {
                "name": "vdu-eth1",
                "ns-vld-id": "datanet",
                "position": 0,
            },
        ]
        self.ns._partially_locate_vdu_interfaces(target_vdu)
        self.assertDictEqual(
            target_vdu["interfaces"][0],
            {
                "name": "vdu-eth1",
                "ns-vld-id": "datanet",
                "position": 0,
            },
        )
        self.assertDictEqual(
            target_vdu["interfaces"][3],
            {"name": "vdu-eth2", "ns-vld-id": "net2", "position": 3},
        )

    def test_partially_locate_vdu_interfaces_wthout_position(self):
        """Interfaces do not have positions."""
        target_vdu = deepcopy(target_vdu_wth_persistent_storage)
        target_vdu["interfaces"] = interfaces_wthout_positions
        expected_result = deepcopy(target_vdu["interfaces"])
        self.ns._partially_locate_vdu_interfaces(target_vdu)
        self.assertEqual(target_vdu["interfaces"], expected_result)

    def test_partially_locate_vdu_interfaces_all_has_position(self):
        """All interfaces have position."""
        target_vdu = deepcopy(target_vdu_wth_persistent_storage)
        target_vdu["interfaces"] = interfaces_wth_all_positions
        expected_interfaces = [
            {
                "name": "vdu-eth2",
                "ns-vld-id": "net2",
                "position": 0,
            },
            {
                "name": "vdu-eth3",
                "ns-vld-id": "mgmtnet",
                "position": 1,
            },
            {
                "name": "vdu-eth1",
                "ns-vld-id": "net1",
                "position": 2,
            },
        ]
        self.ns._partially_locate_vdu_interfaces(target_vdu)
        self.assertEqual(target_vdu["interfaces"], expected_interfaces)

    @patch("osm_ng_ro.ns.Ns._get_cloud_init")
    @patch("osm_ng_ro.ns.Ns._parse_jinja2")
    def test_prepare_vdu_cloud_init(self, mock_parse_jinja2, mock_get_cloud_init):
        """Target_vdu has cloud-init and boot-data-drive."""
        target_vdu = deepcopy(target_vdu_wth_persistent_storage)
        target_vdu["cloud-init"] = "sample-cloud-init-path"
        target_vdu["boot-data-drive"] = "vda"
        vdu2cloud_init = {}
        mock_get_cloud_init.return_value = cloud_init_content
        mock_parse_jinja2.return_value = user_data
        expected_result = {
            "user-data": user_data,
            "boot-data-drive": "vda",
        }
        result = self.ns._prepare_vdu_cloud_init(target_vdu, vdu2cloud_init, db, fs)
        self.assertDictEqual(result, expected_result)
        mock_get_cloud_init.assert_called_once_with(
            db=db, fs=fs, location="sample-cloud-init-path"
        )
        mock_parse_jinja2.assert_called_once_with(
            cloud_init_content=cloud_init_content,
            params=None,
            context="sample-cloud-init-path",
        )

    @patch("osm_ng_ro.ns.Ns._get_cloud_init")
    @patch("osm_ng_ro.ns.Ns._parse_jinja2")
    def test_prepare_vdu_cloud_init_get_cloud_init_raise_exception(
        self, mock_parse_jinja2, mock_get_cloud_init
    ):
        """Target_vdu has cloud-init and boot-data-drive, get_cloud_init method raises exception."""
        target_vdu = deepcopy(target_vdu_wth_persistent_storage)
        target_vdu["cloud-init"] = "sample-cloud-init-path"
        target_vdu["boot-data-drive"] = "vda"
        vdu2cloud_init = {}
        mock_get_cloud_init.side_effect = NsException(
            "Mismatch descriptor for cloud init."
        )

        with self.assertRaises(NsException) as err:
            self.ns._prepare_vdu_cloud_init(target_vdu, vdu2cloud_init, db, fs)
            self.assertEqual(str(err.exception), "Mismatch descriptor for cloud init.")

        mock_get_cloud_init.assert_called_once_with(
            db=db, fs=fs, location="sample-cloud-init-path"
        )
        mock_parse_jinja2.assert_not_called()

    @patch("osm_ng_ro.ns.Ns._get_cloud_init")
    @patch("osm_ng_ro.ns.Ns._parse_jinja2")
    def test_prepare_vdu_cloud_init_parse_jinja2_raise_exception(
        self, mock_parse_jinja2, mock_get_cloud_init
    ):
        """Target_vdu has cloud-init and boot-data-drive, parse_jinja2 method raises exception."""
        target_vdu = deepcopy(target_vdu_wth_persistent_storage)
        target_vdu["cloud-init"] = "sample-cloud-init-path"
        target_vdu["boot-data-drive"] = "vda"
        vdu2cloud_init = {}
        mock_get_cloud_init.return_value = cloud_init_content
        mock_parse_jinja2.side_effect = NsException("Error parsing cloud-init content.")

        with self.assertRaises(NsException) as err:
            self.ns._prepare_vdu_cloud_init(target_vdu, vdu2cloud_init, db, fs)
            self.assertEqual(str(err.exception), "Error parsing cloud-init content.")
        mock_get_cloud_init.assert_called_once_with(
            db=db, fs=fs, location="sample-cloud-init-path"
        )
        mock_parse_jinja2.assert_called_once_with(
            cloud_init_content=cloud_init_content,
            params=None,
            context="sample-cloud-init-path",
        )

    @patch("osm_ng_ro.ns.Ns._get_cloud_init")
    @patch("osm_ng_ro.ns.Ns._parse_jinja2")
    def test_prepare_vdu_cloud_init_vdu_wthout_boot_data_drive(
        self, mock_parse_jinja2, mock_get_cloud_init
    ):
        """Target_vdu has cloud-init but do not have boot-data-drive."""
        target_vdu = deepcopy(target_vdu_wth_persistent_storage)
        target_vdu["cloud-init"] = "sample-cloud-init-path"
        vdu2cloud_init = {}
        mock_get_cloud_init.return_value = cloud_init_content
        mock_parse_jinja2.return_value = user_data
        expected_result = {
            "user-data": user_data,
        }
        result = self.ns._prepare_vdu_cloud_init(target_vdu, vdu2cloud_init, db, fs)
        self.assertDictEqual(result, expected_result)
        mock_get_cloud_init.assert_called_once_with(
            db=db, fs=fs, location="sample-cloud-init-path"
        )
        mock_parse_jinja2.assert_called_once_with(
            cloud_init_content=cloud_init_content,
            params=None,
            context="sample-cloud-init-path",
        )

    @patch("osm_ng_ro.ns.Ns._get_cloud_init")
    @patch("osm_ng_ro.ns.Ns._parse_jinja2")
    def test_prepare_vdu_cloud_init_exists_in_vdu2cloud_init(
        self, mock_parse_jinja2, mock_get_cloud_init
    ):
        """Target_vdu has cloud-init, vdu2cloud_init dict has cloud-init_content."""
        target_vdu = deepcopy(target_vdu_wth_persistent_storage)
        target_vdu["cloud-init"] = "sample-cloud-init-path"
        target_vdu["boot-data-drive"] = "vda"
        vdu2cloud_init = {"sample-cloud-init-path": cloud_init_content}
        mock_parse_jinja2.return_value = user_data
        expected_result = {
            "user-data": user_data,
            "boot-data-drive": "vda",
        }
        result = self.ns._prepare_vdu_cloud_init(target_vdu, vdu2cloud_init, db, fs)
        self.assertDictEqual(result, expected_result)
        mock_get_cloud_init.assert_not_called()
        mock_parse_jinja2.assert_called_once_with(
            cloud_init_content=cloud_init_content,
            params=None,
            context="sample-cloud-init-path",
        )

    @patch("osm_ng_ro.ns.Ns._get_cloud_init")
    @patch("osm_ng_ro.ns.Ns._parse_jinja2")
    def test_prepare_vdu_cloud_init_no_cloud_init(
        self, mock_parse_jinja2, mock_get_cloud_init
    ):
        """Target_vdu do not have cloud-init."""
        target_vdu = deepcopy(target_vdu_wth_persistent_storage)
        target_vdu["boot-data-drive"] = "vda"
        vdu2cloud_init = {}
        expected_result = {
            "boot-data-drive": "vda",
        }
        result = self.ns._prepare_vdu_cloud_init(target_vdu, vdu2cloud_init, db, fs)
        self.assertDictEqual(result, expected_result)
        mock_get_cloud_init.assert_not_called()
        mock_parse_jinja2.assert_not_called()

    def test_check_vld_information_of_interfaces_ns_vld_vnf_vld_both_exist(self):
        """ns_vld and vnf_vld both exist."""
        interface = {
            "name": "vdu-eth0",
            "ns-vld-id": "mgmtnet",
            "vnf-vld-id": "mgmt_cp_int",
        }
        expected_result = f"{ns_preffix}:vld.mgmtnet"
        result = self.ns._check_vld_information_of_interfaces(
            interface, ns_preffix, vnf_preffix
        )
        self.assertEqual(result, expected_result)

    def test_check_vld_information_of_interfaces_empty_interfaces(self):
        """Interface dict is empty."""
        interface = {}
        result = self.ns._check_vld_information_of_interfaces(
            interface, ns_preffix, vnf_preffix
        )
        self.assertEqual(result, "")

    def test_check_vld_information_of_interfaces_has_only_vnf_vld(self):
        """Interface dict has only vnf_vld."""
        interface = {
            "name": "vdu-eth0",
            "vnf-vld-id": "mgmt_cp_int",
        }
        expected_result = f"{vnf_preffix}:vld.mgmt_cp_int"
        result = self.ns._check_vld_information_of_interfaces(
            interface, ns_preffix, vnf_preffix
        )
        self.assertEqual(result, expected_result)

    def test_check_vld_information_of_interfaces_has_vnf_vld_wthout_vnf_prefix(
        self,
    ):
        """Interface dict has only vnf_vld but vnf_preffix does not exist."""
        interface = {
            "name": "vdu-eth0",
            "vnf-vld-id": "mgmt_cp_int",
        }
        vnf_preffix = None
        with self.assertRaises(Exception) as err:
            self.ns._check_vld_information_of_interfaces(
                interface, ns_preffix, vnf_preffix
            )
            self.assertEqual(type(err), TypeError)

    def test_prepare_interface_port_security_has_security_details(self):
        """Interface dict has port security details."""
        interface = {
            "name": "vdu-eth0",
            "ns-vld-id": "mgmtnet",
            "vnf-vld-id": "mgmt_cp_int",
            "port-security-enabled": True,
            "port-security-disable-strategy": "allow-address-pairs",
        }
        expected_interface = {
            "name": "vdu-eth0",
            "ns-vld-id": "mgmtnet",
            "vnf-vld-id": "mgmt_cp_int",
            "port_security": True,
            "port_security_disable_strategy": "allow-address-pairs",
        }
        self.ns._prepare_interface_port_security(interface)
        self.assertDictEqual(interface, expected_interface)

    def test_prepare_interface_port_security_empty_interfaces(self):
        """Interface dict is empty."""
        interface = {}
        expected_interface = {}
        self.ns._prepare_interface_port_security(interface)
        self.assertDictEqual(interface, expected_interface)

    def test_prepare_interface_port_security_wthout_port_security(self):
        """Interface dict does not have port security details."""
        interface = {
            "name": "vdu-eth0",
            "ns-vld-id": "mgmtnet",
            "vnf-vld-id": "mgmt_cp_int",
        }
        expected_interface = {
            "name": "vdu-eth0",
            "ns-vld-id": "mgmtnet",
            "vnf-vld-id": "mgmt_cp_int",
        }
        self.ns._prepare_interface_port_security(interface)
        self.assertDictEqual(interface, expected_interface)

    def test_create_net_item_of_interface_floating_ip_port_security(self):
        """Interface dict has floating ip, port-security details."""
        interface = {
            "name": "vdu-eth0",
            "vcpi": "sample_vcpi",
            "port_security": True,
            "port_security_disable_strategy": "allow-address-pairs",
            "floating_ip": "10.1.1.12",
            "ns-vld-id": "mgmtnet",
            "vnf-vld-id": "mgmt_cp_int",
        }
        net_text = f"{ns_preffix}"
        expected_net_item = {
            "name": "vdu-eth0",
            "port_security": True,
            "port_security_disable_strategy": "allow-address-pairs",
            "floating_ip": "10.1.1.12",
            "net_id": f"TASK-{ns_preffix}",
            "type": "virtual",
        }
        result = self.ns._create_net_item_of_interface(interface, net_text)
        self.assertDictEqual(result, expected_net_item)

    def test_create_net_item_of_interface_invalid_net_text(self):
        """net-text is invalid."""
        interface = {
            "name": "vdu-eth0",
            "vcpi": "sample_vcpi",
            "port_security": True,
            "port_security_disable_strategy": "allow-address-pairs",
            "floating_ip": "10.1.1.12",
            "ns-vld-id": "mgmtnet",
            "vnf-vld-id": "mgmt_cp_int",
        }
        net_text = None
        with self.assertRaises(TypeError):
            self.ns._create_net_item_of_interface(interface, net_text)

    def test_create_net_item_of_interface_empty_interface(self):
        """Interface dict is empty."""
        interface = {}
        net_text = ns_preffix
        expected_net_item = {
            "net_id": f"TASK-{ns_preffix}",
            "type": "virtual",
        }
        result = self.ns._create_net_item_of_interface(interface, net_text)
        self.assertDictEqual(result, expected_net_item)

    @patch("osm_ng_ro.ns.deep_get")
    def test_prepare_type_of_interface_type_sriov(self, mock_deep_get):
        """Interface type is SR-IOV."""
        interface = {
            "name": "vdu-eth0",
            "vcpi": "sample_vcpi",
            "port_security": True,
            "port_security_disable_strategy": "allow-address-pairs",
            "floating_ip": "10.1.1.12",
            "ns-vld-id": "mgmtnet",
            "vnf-vld-id": "mgmt_cp_int",
            "type": "SR-IOV",
        }
        mock_deep_get.return_value = "SR-IOV"
        net_text = ns_preffix
        net_item = {}
        expected_net_item = {
            "use": "data",
            "model": "SR-IOV",
            "type": "SR-IOV",
        }
        self.ns._prepare_type_of_interface(
            interface, tasks_by_target_record_id, net_text, net_item
        )
        self.assertDictEqual(net_item, expected_net_item)
        self.assertEqual(
            "data",
            tasks_by_target_record_id[net_text]["extra_dict"]["params"]["net_type"],
        )
        mock_deep_get.assert_called_once_with(
            tasks_by_target_record_id, net_text, "extra_dict", "params", "net_type"
        )

    @patch("osm_ng_ro.ns.deep_get")
    def test_prepare_type_of_interface_type_pic_passthrough_deep_get_return_empty_dict(
        self, mock_deep_get
    ):
        """Interface type is PCI-PASSTHROUGH, deep_get method return empty dict."""
        interface = {
            "name": "vdu-eth0",
            "vcpi": "sample_vcpi",
            "port_security": True,
            "port_security_disable_strategy": "allow-address-pairs",
            "floating_ip": "10.1.1.12",
            "ns-vld-id": "mgmtnet",
            "vnf-vld-id": "mgmt_cp_int",
            "type": "PCI-PASSTHROUGH",
        }
        mock_deep_get.return_value = {}
        tasks_by_target_record_id = {}
        net_text = ns_preffix
        net_item = {}
        expected_net_item = {
            "use": "data",
            "model": "PCI-PASSTHROUGH",
            "type": "PCI-PASSTHROUGH",
        }
        self.ns._prepare_type_of_interface(
            interface, tasks_by_target_record_id, net_text, net_item
        )
        self.assertDictEqual(net_item, expected_net_item)
        mock_deep_get.assert_called_once_with(
            tasks_by_target_record_id, net_text, "extra_dict", "params", "net_type"
        )

    @patch("osm_ng_ro.ns.deep_get")
    def test_prepare_type_of_interface_type_mgmt(self, mock_deep_get):
        """Interface type is mgmt."""
        interface = {
            "name": "vdu-eth0",
            "vcpi": "sample_vcpi",
            "port_security": True,
            "port_security_disable_strategy": "allow-address-pairs",
            "floating_ip": "10.1.1.12",
            "ns-vld-id": "mgmtnet",
            "vnf-vld-id": "mgmt_cp_int",
            "type": "OM-MGMT",
        }
        tasks_by_target_record_id = {}
        net_text = ns_preffix
        net_item = {}
        expected_net_item = {
            "use": "mgmt",
        }
        self.ns._prepare_type_of_interface(
            interface, tasks_by_target_record_id, net_text, net_item
        )
        self.assertDictEqual(net_item, expected_net_item)
        mock_deep_get.assert_not_called()

    @patch("osm_ng_ro.ns.deep_get")
    def test_prepare_type_of_interface_type_bridge(self, mock_deep_get):
        """Interface type is bridge."""
        interface = {
            "name": "vdu-eth0",
            "vcpi": "sample_vcpi",
            "port_security": True,
            "port_security_disable_strategy": "allow-address-pairs",
            "floating_ip": "10.1.1.12",
            "ns-vld-id": "mgmtnet",
            "vnf-vld-id": "mgmt_cp_int",
        }
        tasks_by_target_record_id = {}
        net_text = ns_preffix
        net_item = {}
        expected_net_item = {
            "use": "bridge",
            "model": None,
        }
        self.ns._prepare_type_of_interface(
            interface, tasks_by_target_record_id, net_text, net_item
        )
        self.assertDictEqual(net_item, expected_net_item)
        mock_deep_get.assert_not_called()

    @patch("osm_ng_ro.ns.Ns._check_vld_information_of_interfaces")
    @patch("osm_ng_ro.ns.Ns._prepare_interface_port_security")
    @patch("osm_ng_ro.ns.Ns._create_net_item_of_interface")
    @patch("osm_ng_ro.ns.Ns._prepare_type_of_interface")
    def test_prepare_vdu_interfaces(
        self,
        mock_type_of_interface,
        mock_item_of_interface,
        mock_port_security,
        mock_vld_information_of_interface,
    ):
        """Prepare vdu interfaces successfully."""
        target_vdu = deepcopy(target_vdu_wth_persistent_storage)
        interface_1 = {
            "name": "vdu-eth1",
            "ns-vld-id": "net1",
            "ip-address": "13.2.12.31",
            "mgmt-interface": True,
        }
        interface_2 = {
            "name": "vdu-eth2",
            "vnf-vld-id": "net2",
            "mac-address": "d0:94:66:ed:fc:e2",
        }
        interface_3 = {
            "name": "vdu-eth3",
            "ns-vld-id": "mgmtnet",
        }
        target_vdu["interfaces"] = [interface_1, interface_2, interface_3]
        extra_dict = {
            "params": "test_params",
            "find_params": "test_find_params",
            "depends_on": [],
        }

        net_text_1 = f"{ns_preffix}:net1"
        net_text_2 = f"{vnf_preffix}:net2"
        net_text_3 = f"{ns_preffix}:mgmtnet"
        net_item_1 = {
            "name": "vdu-eth1",
            "net_id": f"TASK-{ns_preffix}",
            "type": "virtual",
        }
        net_item_2 = {
            "name": "vdu-eth2",
            "net_id": f"TASK-{ns_preffix}",
            "type": "virtual",
        }
        net_item_3 = {
            "name": "vdu-eth3",
            "net_id": f"TASK-{ns_preffix}",
            "type": "virtual",
        }
        mock_item_of_interface.side_effect = [net_item_1, net_item_2, net_item_3]
        mock_vld_information_of_interface.side_effect = [
            net_text_1,
            net_text_2,
            net_text_3,
        ]
        net_list = []
        expected_extra_dict = {
            "params": "test_params",
            "find_params": "test_find_params",
            "depends_on": [net_text_1, net_text_2, net_text_3],
            "mgmt_vdu_interface": 0,
        }
        updated_net_item1 = deepcopy(net_item_1)
        updated_net_item1.update({"ip_address": "13.2.12.31"})
        updated_net_item2 = deepcopy(net_item_2)
        updated_net_item2.update({"mac_address": "d0:94:66:ed:fc:e2"})
        expected_net_list = [updated_net_item1, updated_net_item2, net_item_3]
        self.ns._prepare_vdu_interfaces(
            target_vdu,
            extra_dict,
            ns_preffix,
            vnf_preffix,
            self.logger,
            tasks_by_target_record_id,
            net_list,
        )
        _call_mock_vld_information_of_interface = (
            mock_vld_information_of_interface.call_args_list
        )
        self.assertEqual(
            _call_mock_vld_information_of_interface[0][0],
            (interface_1, ns_preffix, vnf_preffix),
        )
        self.assertEqual(
            _call_mock_vld_information_of_interface[1][0],
            (interface_2, ns_preffix, vnf_preffix),
        )
        self.assertEqual(
            _call_mock_vld_information_of_interface[2][0],
            (interface_3, ns_preffix, vnf_preffix),
        )

        _call_mock_port_security = mock_port_security.call_args_list
        self.assertEqual(_call_mock_port_security[0].args[0], interface_1)
        self.assertEqual(_call_mock_port_security[1].args[0], interface_2)
        self.assertEqual(_call_mock_port_security[2].args[0], interface_3)

        _call_mock_item_of_interface = mock_item_of_interface.call_args_list
        self.assertEqual(_call_mock_item_of_interface[0][0], (interface_1, net_text_1))
        self.assertEqual(_call_mock_item_of_interface[1][0], (interface_2, net_text_2))
        self.assertEqual(_call_mock_item_of_interface[2][0], (interface_3, net_text_3))

        _call_mock_type_of_interface = mock_type_of_interface.call_args_list
        self.assertEqual(
            _call_mock_type_of_interface[0][0],
            (interface_1, tasks_by_target_record_id, net_text_1, net_item_1),
        )
        self.assertEqual(
            _call_mock_type_of_interface[1][0],
            (interface_2, tasks_by_target_record_id, net_text_2, net_item_2),
        )
        self.assertEqual(
            _call_mock_type_of_interface[2][0],
            (interface_3, tasks_by_target_record_id, net_text_3, net_item_3),
        )
        self.assertEqual(net_list, expected_net_list)
        self.assertEqual(extra_dict, expected_extra_dict)
        self.logger.error.assert_not_called()

    @patch("osm_ng_ro.ns.Ns._check_vld_information_of_interfaces")
    @patch("osm_ng_ro.ns.Ns._prepare_interface_port_security")
    @patch("osm_ng_ro.ns.Ns._create_net_item_of_interface")
    @patch("osm_ng_ro.ns.Ns._prepare_type_of_interface")
    def test_prepare_vdu_interfaces_create_net_item_raise_exception(
        self,
        mock_type_of_interface,
        mock_item_of_interface,
        mock_port_security,
        mock_vld_information_of_interface,
    ):
        """Prepare vdu interfaces, create_net_item_of_interface method raise exception."""
        target_vdu = deepcopy(target_vdu_wth_persistent_storage)
        interface_1 = {
            "name": "vdu-eth1",
            "ns-vld-id": "net1",
            "ip-address": "13.2.12.31",
            "mgmt-interface": True,
        }
        interface_2 = {
            "name": "vdu-eth2",
            "vnf-vld-id": "net2",
            "mac-address": "d0:94:66:ed:fc:e2",
        }
        interface_3 = {
            "name": "vdu-eth3",
            "ns-vld-id": "mgmtnet",
        }
        target_vdu["interfaces"] = [interface_1, interface_2, interface_3]
        extra_dict = {
            "params": "test_params",
            "find_params": "test_find_params",
            "depends_on": [],
        }
        net_text_1 = f"{ns_preffix}:net1"
        mock_item_of_interface.side_effect = [TypeError, TypeError, TypeError]

        mock_vld_information_of_interface.side_effect = [net_text_1]
        net_list = []
        expected_extra_dict = {
            "params": "test_params",
            "find_params": "test_find_params",
            "depends_on": [net_text_1],
        }
        with self.assertRaises(TypeError):
            self.ns._prepare_vdu_interfaces(
                target_vdu,
                extra_dict,
                ns_preffix,
                vnf_preffix,
                self.logger,
                tasks_by_target_record_id,
                net_list,
            )

        _call_mock_vld_information_of_interface = (
            mock_vld_information_of_interface.call_args_list
        )
        self.assertEqual(
            _call_mock_vld_information_of_interface[0][0],
            (interface_1, ns_preffix, vnf_preffix),
        )

        _call_mock_port_security = mock_port_security.call_args_list
        self.assertEqual(_call_mock_port_security[0].args[0], interface_1)

        _call_mock_item_of_interface = mock_item_of_interface.call_args_list
        self.assertEqual(_call_mock_item_of_interface[0][0], (interface_1, net_text_1))

        mock_type_of_interface.assert_not_called()
        self.logger.error.assert_not_called()
        self.assertEqual(net_list, [])
        self.assertEqual(extra_dict, expected_extra_dict)

    @patch("osm_ng_ro.ns.Ns._check_vld_information_of_interfaces")
    @patch("osm_ng_ro.ns.Ns._prepare_interface_port_security")
    @patch("osm_ng_ro.ns.Ns._create_net_item_of_interface")
    @patch("osm_ng_ro.ns.Ns._prepare_type_of_interface")
    def test_prepare_vdu_interfaces_vld_information_is_empty(
        self,
        mock_type_of_interface,
        mock_item_of_interface,
        mock_port_security,
        mock_vld_information_of_interface,
    ):
        """Prepare vdu interfaces, check_vld_information_of_interface method returns empty result."""
        target_vdu = deepcopy(target_vdu_wth_persistent_storage)
        interface_1 = {
            "name": "vdu-eth1",
            "ns-vld-id": "net1",
            "ip-address": "13.2.12.31",
            "mgmt-interface": True,
        }
        interface_2 = {
            "name": "vdu-eth2",
            "vnf-vld-id": "net2",
            "mac-address": "d0:94:66:ed:fc:e2",
        }
        interface_3 = {
            "name": "vdu-eth3",
            "ns-vld-id": "mgmtnet",
        }
        target_vdu["interfaces"] = [interface_1, interface_2, interface_3]
        extra_dict = {
            "params": "test_params",
            "find_params": "test_find_params",
            "depends_on": [],
        }
        mock_vld_information_of_interface.side_effect = ["", "", ""]
        net_list = []
        self.ns._prepare_vdu_interfaces(
            target_vdu,
            extra_dict,
            ns_preffix,
            vnf_preffix,
            self.logger,
            tasks_by_target_record_id,
            net_list,
        )

        _call_mock_vld_information_of_interface = (
            mock_vld_information_of_interface.call_args_list
        )
        self.assertEqual(
            _call_mock_vld_information_of_interface[0][0],
            (interface_1, ns_preffix, vnf_preffix),
        )
        self.assertEqual(
            _call_mock_vld_information_of_interface[1][0],
            (interface_2, ns_preffix, vnf_preffix),
        )
        self.assertEqual(
            _call_mock_vld_information_of_interface[2][0],
            (interface_3, ns_preffix, vnf_preffix),
        )

        _call_logger = self.logger.error.call_args_list
        self.assertEqual(
            _call_logger[0][0],
            ("Interface 0 from vdu several_volumes-VM not connected to any vld",),
        )
        self.assertEqual(
            _call_logger[1][0],
            ("Interface 1 from vdu several_volumes-VM not connected to any vld",),
        )
        self.assertEqual(
            _call_logger[2][0],
            ("Interface 2 from vdu several_volumes-VM not connected to any vld",),
        )
        self.assertEqual(net_list, [])
        self.assertEqual(
            extra_dict,
            {
                "params": "test_params",
                "find_params": "test_find_params",
                "depends_on": [],
            },
        )

        mock_item_of_interface.assert_not_called()
        mock_port_security.assert_not_called()
        mock_type_of_interface.assert_not_called()

    @patch("osm_ng_ro.ns.Ns._check_vld_information_of_interfaces")
    @patch("osm_ng_ro.ns.Ns._prepare_interface_port_security")
    @patch("osm_ng_ro.ns.Ns._create_net_item_of_interface")
    @patch("osm_ng_ro.ns.Ns._prepare_type_of_interface")
    def test_prepare_vdu_interfaces_empty_interface_list(
        self,
        mock_type_of_interface,
        mock_item_of_interface,
        mock_port_security,
        mock_vld_information_of_interface,
    ):
        """Prepare vdu interfaces, interface list is empty."""
        target_vdu = deepcopy(target_vdu_wth_persistent_storage)
        target_vdu["interfaces"] = []
        extra_dict = {}
        net_list = []
        self.ns._prepare_vdu_interfaces(
            target_vdu,
            extra_dict,
            ns_preffix,
            vnf_preffix,
            self.logger,
            tasks_by_target_record_id,
            net_list,
        )
        mock_type_of_interface.assert_not_called()
        mock_vld_information_of_interface.assert_not_called()
        mock_item_of_interface.assert_not_called()
        mock_port_security.assert_not_called()

    def test_prepare_vdu_ssh_keys(self):
        """Target_vdu has ssh-keys and ro_nsr_public_key exists."""
        target_vdu = deepcopy(target_vdu_wth_persistent_storage)
        target_vdu["ssh-keys"] = ["sample-ssh-key"]
        ro_nsr_public_key = {"public_key": "path_of_public_key"}
        target_vdu["ssh-access-required"] = True
        cloud_config = {}
        expected_cloud_config = {
            "key-pairs": ["sample-ssh-key", {"public_key": "path_of_public_key"}]
        }
        self.ns._prepare_vdu_ssh_keys(target_vdu, ro_nsr_public_key, cloud_config)
        self.assertDictEqual(cloud_config, expected_cloud_config)

    def test_prepare_vdu_ssh_keys_target_vdu_wthout_ssh_keys(self):
        """Target_vdu does not have ssh-keys."""
        target_vdu = deepcopy(target_vdu_wth_persistent_storage)
        ro_nsr_public_key = {"public_key": "path_of_public_key"}
        target_vdu["ssh-access-required"] = True
        cloud_config = {}
        expected_cloud_config = {"key-pairs": [{"public_key": "path_of_public_key"}]}
        self.ns._prepare_vdu_ssh_keys(target_vdu, ro_nsr_public_key, cloud_config)
        self.assertDictEqual(cloud_config, expected_cloud_config)

    def test_prepare_vdu_ssh_keys_ssh_access_is_not_required(self):
        """Target_vdu has ssh-keys, ssh-access is not required."""
        target_vdu = deepcopy(target_vdu_wth_persistent_storage)
        target_vdu["ssh-keys"] = ["sample-ssh-key"]
        ro_nsr_public_key = {"public_key": "path_of_public_key"}
        target_vdu["ssh-access-required"] = False
        cloud_config = {}
        expected_cloud_config = {"key-pairs": ["sample-ssh-key"]}
        self.ns._prepare_vdu_ssh_keys(target_vdu, ro_nsr_public_key, cloud_config)
        self.assertDictEqual(cloud_config, expected_cloud_config)

    @patch("osm_ng_ro.ns.Ns._select_persistent_root_disk")
    @patch("osm_ng_ro.ns.Ns.is_volume_keeping_required")
    def test_add_persistent_root_disk_to_disk_list_keep_false(
        self, mock_volume_keeping_required, mock_select_persistent_root_disk
    ):
        """Add persistent root disk to disk_list, keep volume set to False."""
        root_disk = {
            "id": "persistent-root-volume",
            "type-of-storage": "persistent-storage:persistent-storage",
            "size-of-storage": "10",
        }
        mock_select_persistent_root_disk.return_value = root_disk
        vnfd = deepcopy(vnfd_wth_persistent_storage)
        vnfd["virtual-storage-desc"][1] = root_disk
        target_vdu = deepcopy(target_vdu_wth_persistent_storage)
        persistent_root_disk = {}
        disk_list = []
        mock_volume_keeping_required.return_value = False
        expected_disk_list = [
            {
                "image_id": "ubuntu20.04",
                "size": "10",
                "keep": False,
            }
        ]
        self.ns._add_persistent_root_disk_to_disk_list(
            vnfd, target_vdu, persistent_root_disk, disk_list
        )
        self.assertEqual(disk_list, expected_disk_list)
        mock_select_persistent_root_disk.assert_called_once()
        mock_volume_keeping_required.assert_called_once()

    @patch("osm_ng_ro.ns.Ns._select_persistent_root_disk")
    @patch("osm_ng_ro.ns.Ns.is_volume_keeping_required")
    def test_add_persistent_root_disk_to_disk_list_select_persistent_root_disk_raises(
        self, mock_volume_keeping_required, mock_select_persistent_root_disk
    ):
        """Add persistent root disk to disk_list"""
        root_disk = {
            "id": "persistent-root-volume",
            "type-of-storage": "persistent-storage:persistent-storage",
            "size-of-storage": "10",
        }
        mock_select_persistent_root_disk.side_effect = AttributeError
        vnfd = deepcopy(vnfd_wth_persistent_storage)
        vnfd["virtual-storage-desc"][1] = root_disk
        target_vdu = deepcopy(target_vdu_wth_persistent_storage)
        persistent_root_disk = {}
        disk_list = []
        with self.assertRaises(AttributeError):
            self.ns._add_persistent_root_disk_to_disk_list(
                vnfd, target_vdu, persistent_root_disk, disk_list
            )
        self.assertEqual(disk_list, [])
        mock_select_persistent_root_disk.assert_called_once()
        mock_volume_keeping_required.assert_not_called()

    @patch("osm_ng_ro.ns.Ns._select_persistent_root_disk")
    @patch("osm_ng_ro.ns.Ns.is_volume_keeping_required")
    def test_add_persistent_root_disk_to_disk_list_keep_true(
        self, mock_volume_keeping_required, mock_select_persistent_root_disk
    ):
        """Add persistent root disk, keeo volume set to True."""
        vnfd = deepcopy(vnfd_wth_persistent_storage)
        target_vdu = deepcopy(target_vdu_wth_persistent_storage)
        mock_volume_keeping_required.return_value = True
        root_disk = {
            "id": "persistent-root-volume",
            "type-of-storage": "persistent-storage:persistent-storage",
            "size-of-storage": "10",
            "vdu-storage-requirements": [
                {"key": "keep-volume", "value": "true"},
            ],
        }
        mock_select_persistent_root_disk.return_value = root_disk
        persistent_root_disk = {}
        disk_list = []
        expected_disk_list = [
            {
                "image_id": "ubuntu20.04",
                "size": "10",
                "keep": True,
            }
        ]
        self.ns._add_persistent_root_disk_to_disk_list(
            vnfd, target_vdu, persistent_root_disk, disk_list
        )
        self.assertEqual(disk_list, expected_disk_list)
        mock_volume_keeping_required.assert_called_once_with(root_disk)

    @patch("osm_ng_ro.ns.Ns.is_volume_keeping_required")
    def test_add_persistent_ordinary_disk_to_disk_list(
        self, mock_volume_keeping_required
    ):
        """Add persistent ordinary disk, keeo volume set to True."""
        target_vdu = deepcopy(target_vdu_wth_persistent_storage)
        mock_volume_keeping_required.return_value = False
        persistent_root_disk = {
            "persistent-root-volume": {
                "image_id": "ubuntu20.04",
                "size": "10",
                "keep": True,
            }
        }
        ordinary_disk = {
            "id": "persistent-volume2",
            "type-of-storage": "persistent-storage:persistent-storage",
            "size-of-storage": "10",
        }
        persistent_ordinary_disk = {}
        disk_list = []
        extra_dict = {}
        expected_disk_list = [
            {
                "size": "10",
                "keep": False,
                "multiattach": False,
                "name": "persistent-volume2",
            }
        ]
        self.ns._add_persistent_ordinary_disks_to_disk_list(
            target_vdu,
            persistent_root_disk,
            persistent_ordinary_disk,
            disk_list,
            extra_dict,
        )
        self.assertEqual(disk_list, expected_disk_list)
        mock_volume_keeping_required.assert_called_once_with(ordinary_disk)

    @patch("osm_ng_ro.ns.Ns.is_volume_keeping_required")
    def test_add_persistent_ordinary_disk_to_disk_list_vsd_id_in_root_disk_dict(
        self, mock_volume_keeping_required
    ):
        """Add persistent ordinary disk, vsd id is in root_disk dict."""
        target_vdu = deepcopy(target_vdu_wth_persistent_storage)
        mock_volume_keeping_required.return_value = False
        persistent_root_disk = {
            "persistent-root-volume": {
                "image_id": "ubuntu20.04",
                "size": "10",
                "keep": True,
            },
            "persistent-volume2": {
                "size": "10",
            },
        }
        persistent_ordinary_disk = {}
        disk_list = []
        extra_dict = {}

        self.ns._add_persistent_ordinary_disks_to_disk_list(
            target_vdu,
            persistent_root_disk,
            persistent_ordinary_disk,
            disk_list,
            extra_dict,
        )
        self.assertEqual(disk_list, [])
        mock_volume_keeping_required.assert_not_called()

    @patch("osm_ng_ro.ns.Ns._select_persistent_root_disk")
    @patch("osm_ng_ro.ns.Ns.is_volume_keeping_required")
    def test_add_persistent_root_disk_to_disk_list_vnfd_wthout_persistent_storage(
        self, mock_volume_keeping_required, mock_select_persistent_root_disk
    ):
        """VNFD does not have persistent storage."""
        vnfd = deepcopy(vnfd_wthout_persistent_storage)
        target_vdu = deepcopy(target_vdu_wthout_persistent_storage)
        mock_select_persistent_root_disk.return_value = None
        persistent_root_disk = {}
        disk_list = []
        self.ns._add_persistent_root_disk_to_disk_list(
            vnfd, target_vdu, persistent_root_disk, disk_list
        )
        self.assertEqual(disk_list, [])
        self.assertEqual(mock_select_persistent_root_disk.call_count, 2)
        mock_volume_keeping_required.assert_not_called()

    @patch("osm_ng_ro.ns.Ns._select_persistent_root_disk")
    @patch("osm_ng_ro.ns.Ns.is_volume_keeping_required")
    def test_add_persistent_root_disk_to_disk_list_wthout_persistent_root_disk(
        self, mock_volume_keeping_required, mock_select_persistent_root_disk
    ):
        """Persistent_root_disk dict is empty."""
        vnfd = deepcopy(vnfd_wthout_persistent_storage)
        target_vdu = deepcopy(target_vdu_wthout_persistent_storage)
        mock_select_persistent_root_disk.return_value = None
        persistent_root_disk = {}
        disk_list = []
        self.ns._add_persistent_root_disk_to_disk_list(
            vnfd, target_vdu, persistent_root_disk, disk_list
        )
        self.assertEqual(disk_list, [])
        self.assertEqual(mock_select_persistent_root_disk.call_count, 2)
        mock_volume_keeping_required.assert_not_called()

    def test_prepare_vdu_affinity_group_list_invalid_extra_dict(self):
        """Invalid extra dict."""
        target_vdu = deepcopy(target_vdu_wth_persistent_storage)
        target_vdu["affinity-or-anti-affinity-group-id"] = "sample_affinity-group-id"
        extra_dict = {}
        ns_preffix = "nsrs:th47f48-9870-4169-b758-9732e1ff40f3"
        with self.assertRaises(NsException) as err:
            self.ns._prepare_vdu_affinity_group_list(target_vdu, extra_dict, ns_preffix)
            self.assertEqual(str(err.exception), "Invalid extra_dict format.")

    def test_prepare_vdu_affinity_group_list_one_affinity_group(self):
        """There is one affinity-group."""
        target_vdu = deepcopy(target_vdu_wth_persistent_storage)
        target_vdu["affinity-or-anti-affinity-group-id"] = ["sample_affinity-group-id"]
        extra_dict = {"depends_on": []}
        ns_preffix = "nsrs:th47f48-9870-4169-b758-9732e1ff40f3"
        affinity_group_txt = "nsrs:th47f48-9870-4169-b758-9732e1ff40f3:affinity-or-anti-affinity-group.sample_affinity-group-id"
        expected_result = [{"affinity_group_id": "TASK-" + affinity_group_txt}]
        expected_extra_dict = {"depends_on": [affinity_group_txt]}
        result = self.ns._prepare_vdu_affinity_group_list(
            target_vdu, extra_dict, ns_preffix
        )
        self.assertDictEqual(extra_dict, expected_extra_dict)
        self.assertEqual(result, expected_result)

    def test_prepare_vdu_affinity_group_list_several_affinity_groups(self):
        """There are two affinity-groups."""
        target_vdu = deepcopy(target_vdu_wth_persistent_storage)
        target_vdu["affinity-or-anti-affinity-group-id"] = [
            "affinity-group-id1",
            "affinity-group-id2",
        ]
        extra_dict = {"depends_on": []}
        ns_preffix = "nsrs:th47f48-9870-4169-b758-9732e1ff40f3"
        affinity_group_txt1 = "nsrs:th47f48-9870-4169-b758-9732e1ff40f3:affinity-or-anti-affinity-group.affinity-group-id1"
        affinity_group_txt2 = "nsrs:th47f48-9870-4169-b758-9732e1ff40f3:affinity-or-anti-affinity-group.affinity-group-id2"
        expected_result = [
            {"affinity_group_id": "TASK-" + affinity_group_txt1},
            {"affinity_group_id": "TASK-" + affinity_group_txt2},
        ]
        expected_extra_dict = {"depends_on": [affinity_group_txt1, affinity_group_txt2]}
        result = self.ns._prepare_vdu_affinity_group_list(
            target_vdu, extra_dict, ns_preffix
        )
        self.assertDictEqual(extra_dict, expected_extra_dict)
        self.assertEqual(result, expected_result)

    def test_prepare_vdu_affinity_group_list_no_affinity_group(self):
        """There is not any affinity-group."""
        target_vdu = deepcopy(target_vdu_wth_persistent_storage)
        extra_dict = {"depends_on": []}
        ns_preffix = "nsrs:th47f48-9870-4169-b758-9732e1ff40f3"
        result = self.ns._prepare_vdu_affinity_group_list(
            target_vdu, extra_dict, ns_preffix
        )
        self.assertDictEqual(extra_dict, {"depends_on": []})
        self.assertEqual(result, [])

    @patch("osm_ng_ro.ns.Ns._sort_vdu_interfaces")
    @patch("osm_ng_ro.ns.Ns._partially_locate_vdu_interfaces")
    @patch("osm_ng_ro.ns.Ns._prepare_vdu_interfaces")
    @patch("osm_ng_ro.ns.Ns._prepare_vdu_cloud_init")
    @patch("osm_ng_ro.ns.Ns._prepare_vdu_ssh_keys")
    @patch("osm_ng_ro.ns.Ns.find_persistent_root_volumes")
    @patch("osm_ng_ro.ns.Ns.find_persistent_volumes")
    @patch("osm_ng_ro.ns.Ns._add_persistent_root_disk_to_disk_list")
    @patch("osm_ng_ro.ns.Ns._add_persistent_ordinary_disks_to_disk_list")
    @patch("osm_ng_ro.ns.Ns._prepare_vdu_affinity_group_list")
    def test_process_vdu_params_with_inst_vol_list(
        self,
        mock_prepare_vdu_affinity_group_list,
        mock_add_persistent_ordinary_disks_to_disk_list,
        mock_add_persistent_root_disk_to_disk_list,
        mock_find_persistent_volumes,
        mock_find_persistent_root_volumes,
        mock_prepare_vdu_ssh_keys,
        mock_prepare_vdu_cloud_init,
        mock_prepare_vdu_interfaces,
        mock_locate_vdu_interfaces,
        mock_sort_vdu_interfaces,
    ):
        """Instantiation volume list is empty."""
        target_vdu = deepcopy(target_vdu_wth_persistent_storage)

        target_vdu["interfaces"] = interfaces_wth_all_positions

        vdu_instantiation_vol_list = [
            {
                "vim-volume-id": vim_volume_id,
                "name": "persistent-volume2",
            }
        ]
        target_vdu["additionalParams"] = {
            "OSM": {"vdu_volumes": vdu_instantiation_vol_list}
        }
        mock_prepare_vdu_cloud_init.return_value = {}
        mock_prepare_vdu_affinity_group_list.return_value = []
        persistent_root_disk = {
            "persistent-root-volume": {
                "image_id": "ubuntu20.04",
                "size": "10",
            }
        }
        mock_find_persistent_root_volumes.return_value = persistent_root_disk

        new_kwargs = deepcopy(kwargs)
        new_kwargs.update(
            {
                "vnfr_id": vnfr_id,
                "nsr_id": nsr_id,
                "tasks_by_target_record_id": {},
                "logger": "logger",
            }
        )
        expected_extra_dict_copy = deepcopy(expected_extra_dict)
        vnfd = deepcopy(vnfd_wth_persistent_storage)
        db.get_one.return_value = vnfd
        result = Ns._process_vdu_params(
            target_vdu, indata, vim_info=None, target_record_id=None, **new_kwargs
        )
        mock_sort_vdu_interfaces.assert_called_once_with(target_vdu)
        mock_locate_vdu_interfaces.assert_not_called()
        mock_prepare_vdu_cloud_init.assert_called_once()
        mock_add_persistent_root_disk_to_disk_list.assert_not_called()
        mock_add_persistent_ordinary_disks_to_disk_list.assert_not_called()
        mock_prepare_vdu_interfaces.assert_called_once_with(
            target_vdu,
            expected_extra_dict_copy,
            ns_preffix,
            vnf_preffix,
            "logger",
            {},
            [],
        )
        self.assertDictEqual(result, expected_extra_dict_copy)
        mock_prepare_vdu_ssh_keys.assert_called_once_with(target_vdu, None, {})
        mock_prepare_vdu_affinity_group_list.assert_called_once()
        mock_find_persistent_volumes.assert_called_once_with(
            persistent_root_disk, target_vdu, vdu_instantiation_vol_list, []
        )

    @patch("osm_ng_ro.ns.Ns._sort_vdu_interfaces")
    @patch("osm_ng_ro.ns.Ns._partially_locate_vdu_interfaces")
    @patch("osm_ng_ro.ns.Ns._prepare_vdu_interfaces")
    @patch("osm_ng_ro.ns.Ns._prepare_vdu_cloud_init")
    @patch("osm_ng_ro.ns.Ns._prepare_vdu_ssh_keys")
    @patch("osm_ng_ro.ns.Ns.find_persistent_root_volumes")
    @patch("osm_ng_ro.ns.Ns.find_persistent_volumes")
    @patch("osm_ng_ro.ns.Ns._add_persistent_root_disk_to_disk_list")
    @patch("osm_ng_ro.ns.Ns._add_persistent_ordinary_disks_to_disk_list")
    @patch("osm_ng_ro.ns.Ns._prepare_vdu_affinity_group_list")
    def test_process_vdu_params_wth_affinity_groups(
        self,
        mock_prepare_vdu_affinity_group_list,
        mock_add_persistent_ordinary_disks_to_disk_list,
        mock_add_persistent_root_disk_to_disk_list,
        mock_find_persistent_volumes,
        mock_find_persistent_root_volumes,
        mock_prepare_vdu_ssh_keys,
        mock_prepare_vdu_cloud_init,
        mock_prepare_vdu_interfaces,
        mock_locate_vdu_interfaces,
        mock_sort_vdu_interfaces,
    ):
        """There is cloud-config."""
        target_vdu = deepcopy(target_vdu_wthout_persistent_storage)

        self.maxDiff = None
        target_vdu["interfaces"] = interfaces_wth_all_positions
        mock_prepare_vdu_cloud_init.return_value = {}
        mock_prepare_vdu_affinity_group_list.return_value = [
            "affinity_group_1",
            "affinity_group_2",
        ]

        new_kwargs = deepcopy(kwargs)
        new_kwargs.update(
            {
                "vnfr_id": vnfr_id,
                "nsr_id": nsr_id,
                "tasks_by_target_record_id": {},
                "logger": "logger",
            }
        )
        expected_extra_dict3 = deepcopy(expected_extra_dict2)
        expected_extra_dict3["params"]["affinity_group_list"] = [
            "affinity_group_1",
            "affinity_group_2",
        ]
        vnfd = deepcopy(vnfd_wth_persistent_storage)
        db.get_one.return_value = vnfd
        result = Ns._process_vdu_params(
            target_vdu, indata, vim_info=None, target_record_id=None, **new_kwargs
        )
        self.assertDictEqual(result, expected_extra_dict3)
        mock_sort_vdu_interfaces.assert_called_once_with(target_vdu)
        mock_locate_vdu_interfaces.assert_not_called()
        mock_prepare_vdu_cloud_init.assert_called_once()
        mock_add_persistent_root_disk_to_disk_list.assert_called_once()
        mock_add_persistent_ordinary_disks_to_disk_list.assert_called_once()
        mock_prepare_vdu_interfaces.assert_called_once_with(
            target_vdu,
            expected_extra_dict3,
            ns_preffix,
            vnf_preffix,
            "logger",
            {},
            [],
        )

        mock_prepare_vdu_ssh_keys.assert_called_once_with(target_vdu, None, {})
        mock_prepare_vdu_affinity_group_list.assert_called_once()
        mock_find_persistent_volumes.assert_not_called()

    @patch("osm_ng_ro.ns.Ns._sort_vdu_interfaces")
    @patch("osm_ng_ro.ns.Ns._partially_locate_vdu_interfaces")
    @patch("osm_ng_ro.ns.Ns._prepare_vdu_interfaces")
    @patch("osm_ng_ro.ns.Ns._prepare_vdu_cloud_init")
    @patch("osm_ng_ro.ns.Ns._prepare_vdu_ssh_keys")
    @patch("osm_ng_ro.ns.Ns.find_persistent_root_volumes")
    @patch("osm_ng_ro.ns.Ns.find_persistent_volumes")
    @patch("osm_ng_ro.ns.Ns._add_persistent_root_disk_to_disk_list")
    @patch("osm_ng_ro.ns.Ns._add_persistent_ordinary_disks_to_disk_list")
    @patch("osm_ng_ro.ns.Ns._prepare_vdu_affinity_group_list")
    def test_process_vdu_params_wth_cloud_config(
        self,
        mock_prepare_vdu_affinity_group_list,
        mock_add_persistent_ordinary_disks_to_disk_list,
        mock_add_persistent_root_disk_to_disk_list,
        mock_find_persistent_volumes,
        mock_find_persistent_root_volumes,
        mock_prepare_vdu_ssh_keys,
        mock_prepare_vdu_cloud_init,
        mock_prepare_vdu_interfaces,
        mock_locate_vdu_interfaces,
        mock_sort_vdu_interfaces,
    ):
        """There is cloud-config."""
        target_vdu = deepcopy(target_vdu_wthout_persistent_storage)

        self.maxDiff = None
        target_vdu["interfaces"] = interfaces_wth_all_positions
        mock_prepare_vdu_cloud_init.return_value = {
            "user-data": user_data,
            "boot-data-drive": "vda",
        }
        mock_prepare_vdu_affinity_group_list.return_value = []

        new_kwargs = deepcopy(kwargs)
        new_kwargs.update(
            {
                "vnfr_id": vnfr_id,
                "nsr_id": nsr_id,
                "tasks_by_target_record_id": {},
                "logger": "logger",
            }
        )
        expected_extra_dict3 = deepcopy(expected_extra_dict2)
        expected_extra_dict3["params"]["cloud_config"] = {
            "user-data": user_data,
            "boot-data-drive": "vda",
        }
        vnfd = deepcopy(vnfd_wth_persistent_storage)
        db.get_one.return_value = vnfd
        result = Ns._process_vdu_params(
            target_vdu, indata, vim_info=None, target_record_id=None, **new_kwargs
        )
        mock_sort_vdu_interfaces.assert_called_once_with(target_vdu)
        mock_locate_vdu_interfaces.assert_not_called()
        mock_prepare_vdu_cloud_init.assert_called_once()
        mock_add_persistent_root_disk_to_disk_list.assert_called_once()
        mock_add_persistent_ordinary_disks_to_disk_list.assert_called_once()
        mock_prepare_vdu_interfaces.assert_called_once_with(
            target_vdu,
            expected_extra_dict3,
            ns_preffix,
            vnf_preffix,
            "logger",
            {},
            [],
        )
        self.assertDictEqual(result, expected_extra_dict3)
        mock_prepare_vdu_ssh_keys.assert_called_once_with(
            target_vdu, None, {"user-data": user_data, "boot-data-drive": "vda"}
        )
        mock_prepare_vdu_affinity_group_list.assert_called_once()
        mock_find_persistent_volumes.assert_not_called()

    @patch("osm_ng_ro.ns.Ns._sort_vdu_interfaces")
    @patch("osm_ng_ro.ns.Ns._partially_locate_vdu_interfaces")
    @patch("osm_ng_ro.ns.Ns._prepare_vdu_interfaces")
    @patch("osm_ng_ro.ns.Ns._prepare_vdu_cloud_init")
    @patch("osm_ng_ro.ns.Ns._prepare_vdu_ssh_keys")
    @patch("osm_ng_ro.ns.Ns.find_persistent_root_volumes")
    @patch("osm_ng_ro.ns.Ns.find_persistent_volumes")
    @patch("osm_ng_ro.ns.Ns._add_persistent_root_disk_to_disk_list")
    @patch("osm_ng_ro.ns.Ns._add_persistent_ordinary_disks_to_disk_list")
    @patch("osm_ng_ro.ns.Ns._prepare_vdu_affinity_group_list")
    def test_process_vdu_params_wthout_persistent_storage(
        self,
        mock_prepare_vdu_affinity_group_list,
        mock_add_persistent_ordinary_disks_to_disk_list,
        mock_add_persistent_root_disk_to_disk_list,
        mock_find_persistent_volumes,
        mock_find_persistent_root_volumes,
        mock_prepare_vdu_ssh_keys,
        mock_prepare_vdu_cloud_init,
        mock_prepare_vdu_interfaces,
        mock_locate_vdu_interfaces,
        mock_sort_vdu_interfaces,
    ):
        """There is not any persistent storage."""
        target_vdu = deepcopy(target_vdu_wthout_persistent_storage)

        self.maxDiff = None
        target_vdu["interfaces"] = interfaces_wth_all_positions
        mock_prepare_vdu_cloud_init.return_value = {}
        mock_prepare_vdu_affinity_group_list.return_value = []

        new_kwargs = deepcopy(kwargs)
        new_kwargs.update(
            {
                "vnfr_id": vnfr_id,
                "nsr_id": nsr_id,
                "tasks_by_target_record_id": {},
                "logger": "logger",
            }
        )
        expected_extra_dict_copy = deepcopy(expected_extra_dict2)
        vnfd = deepcopy(vnfd_wthout_persistent_storage)
        db.get_one.return_value = vnfd
        result = Ns._process_vdu_params(
            target_vdu, indata, vim_info=None, target_record_id=None, **new_kwargs
        )
        mock_sort_vdu_interfaces.assert_called_once_with(target_vdu)
        mock_locate_vdu_interfaces.assert_not_called()
        mock_prepare_vdu_cloud_init.assert_called_once()
        mock_add_persistent_root_disk_to_disk_list.assert_called_once()
        mock_add_persistent_ordinary_disks_to_disk_list.assert_called_once()
        mock_prepare_vdu_interfaces.assert_called_once_with(
            target_vdu,
            expected_extra_dict_copy,
            ns_preffix,
            vnf_preffix,
            "logger",
            {},
            [],
        )
        self.assertDictEqual(result, expected_extra_dict_copy)
        mock_prepare_vdu_ssh_keys.assert_called_once_with(target_vdu, None, {})
        mock_prepare_vdu_affinity_group_list.assert_called_once()
        mock_find_persistent_volumes.assert_not_called()

    @patch("osm_ng_ro.ns.Ns._sort_vdu_interfaces")
    @patch("osm_ng_ro.ns.Ns._partially_locate_vdu_interfaces")
    @patch("osm_ng_ro.ns.Ns._prepare_vdu_interfaces")
    @patch("osm_ng_ro.ns.Ns._prepare_vdu_cloud_init")
    @patch("osm_ng_ro.ns.Ns._prepare_vdu_ssh_keys")
    @patch("osm_ng_ro.ns.Ns.find_persistent_root_volumes")
    @patch("osm_ng_ro.ns.Ns.find_persistent_volumes")
    @patch("osm_ng_ro.ns.Ns._add_persistent_root_disk_to_disk_list")
    @patch("osm_ng_ro.ns.Ns._add_persistent_ordinary_disks_to_disk_list")
    @patch("osm_ng_ro.ns.Ns._prepare_vdu_affinity_group_list")
    def test_process_vdu_params_interfaces_partially_located(
        self,
        mock_prepare_vdu_affinity_group_list,
        mock_add_persistent_ordinary_disks_to_disk_list,
        mock_add_persistent_root_disk_to_disk_list,
        mock_find_persistent_volumes,
        mock_find_persistent_root_volumes,
        mock_prepare_vdu_ssh_keys,
        mock_prepare_vdu_cloud_init,
        mock_prepare_vdu_interfaces,
        mock_locate_vdu_interfaces,
        mock_sort_vdu_interfaces,
    ):
        """Some interfaces have position."""
        target_vdu = deepcopy(target_vdu_wth_persistent_storage)

        self.maxDiff = None
        target_vdu["interfaces"] = [
            {
                "name": "vdu-eth1",
                "ns-vld-id": "net1",
            },
            {"name": "vdu-eth2", "ns-vld-id": "net2", "position": 2},
            {
                "name": "vdu-eth3",
                "ns-vld-id": "mgmtnet",
            },
        ]
        mock_prepare_vdu_cloud_init.return_value = {}
        mock_prepare_vdu_affinity_group_list.return_value = []
        persistent_root_disk = {
            "persistent-root-volume": {
                "image_id": "ubuntu20.04",
                "size": "10",
                "keep": True,
            }
        }
        mock_find_persistent_root_volumes.return_value = persistent_root_disk

        new_kwargs = deepcopy(kwargs)
        new_kwargs.update(
            {
                "vnfr_id": vnfr_id,
                "nsr_id": nsr_id,
                "tasks_by_target_record_id": {},
                "logger": "logger",
            }
        )

        vnfd = deepcopy(vnfd_wth_persistent_storage)
        db.get_one.return_value = vnfd
        result = Ns._process_vdu_params(
            target_vdu, indata, vim_info=None, target_record_id=None, **new_kwargs
        )
        expected_extra_dict_copy = deepcopy(expected_extra_dict)
        mock_sort_vdu_interfaces.assert_not_called()
        mock_locate_vdu_interfaces.assert_called_once_with(target_vdu)
        mock_prepare_vdu_cloud_init.assert_called_once()
        mock_add_persistent_root_disk_to_disk_list.assert_called_once()
        mock_add_persistent_ordinary_disks_to_disk_list.assert_called_once()
        mock_prepare_vdu_interfaces.assert_called_once_with(
            target_vdu,
            expected_extra_dict_copy,
            ns_preffix,
            vnf_preffix,
            "logger",
            {},
            [],
        )
        self.assertDictEqual(result, expected_extra_dict_copy)
        mock_prepare_vdu_ssh_keys.assert_called_once_with(target_vdu, None, {})
        mock_prepare_vdu_affinity_group_list.assert_called_once()
        mock_find_persistent_volumes.assert_not_called()
        mock_find_persistent_root_volumes.assert_not_called()

    @patch("osm_ng_ro.ns.Ns._sort_vdu_interfaces")
    @patch("osm_ng_ro.ns.Ns._partially_locate_vdu_interfaces")
    @patch("osm_ng_ro.ns.Ns._prepare_vdu_interfaces")
    @patch("osm_ng_ro.ns.Ns._prepare_vdu_cloud_init")
    @patch("osm_ng_ro.ns.Ns._prepare_vdu_ssh_keys")
    @patch("osm_ng_ro.ns.Ns.find_persistent_root_volumes")
    @patch("osm_ng_ro.ns.Ns.find_persistent_volumes")
    @patch("osm_ng_ro.ns.Ns._add_persistent_root_disk_to_disk_list")
    @patch("osm_ng_ro.ns.Ns._add_persistent_ordinary_disks_to_disk_list")
    @patch("osm_ng_ro.ns.Ns._prepare_vdu_affinity_group_list")
    def test_process_vdu_params_no_interface_position(
        self,
        mock_prepare_vdu_affinity_group_list,
        mock_add_persistent_ordinary_disks_to_disk_list,
        mock_add_persistent_root_disk_to_disk_list,
        mock_find_persistent_volumes,
        mock_find_persistent_root_volumes,
        mock_prepare_vdu_ssh_keys,
        mock_prepare_vdu_cloud_init,
        mock_prepare_vdu_interfaces,
        mock_locate_vdu_interfaces,
        mock_sort_vdu_interfaces,
    ):
        """Interfaces do not have position."""
        target_vdu = deepcopy(target_vdu_wth_persistent_storage)

        self.maxDiff = None
        target_vdu["interfaces"] = interfaces_wthout_positions
        mock_prepare_vdu_cloud_init.return_value = {}
        mock_prepare_vdu_affinity_group_list.return_value = []
        persistent_root_disk = {
            "persistent-root-volume": {
                "image_id": "ubuntu20.04",
                "size": "10",
                "keep": True,
            }
        }
        mock_find_persistent_root_volumes.return_value = persistent_root_disk
        new_kwargs = deepcopy(kwargs)
        new_kwargs.update(
            {
                "vnfr_id": vnfr_id,
                "nsr_id": nsr_id,
                "tasks_by_target_record_id": {},
                "logger": "logger",
            }
        )

        vnfd = deepcopy(vnfd_wth_persistent_storage)
        db.get_one.return_value = vnfd
        result = Ns._process_vdu_params(
            target_vdu, indata, vim_info=None, target_record_id=None, **new_kwargs
        )
        expected_extra_dict_copy = deepcopy(expected_extra_dict)
        mock_sort_vdu_interfaces.assert_not_called()
        mock_locate_vdu_interfaces.assert_called_once_with(target_vdu)
        mock_prepare_vdu_cloud_init.assert_called_once()
        mock_add_persistent_root_disk_to_disk_list.assert_called_once()
        mock_add_persistent_ordinary_disks_to_disk_list.assert_called_once()
        mock_prepare_vdu_interfaces.assert_called_once_with(
            target_vdu,
            expected_extra_dict_copy,
            ns_preffix,
            vnf_preffix,
            "logger",
            {},
            [],
        )
        self.assertDictEqual(result, expected_extra_dict_copy)
        mock_prepare_vdu_ssh_keys.assert_called_once_with(target_vdu, None, {})
        mock_prepare_vdu_affinity_group_list.assert_called_once()
        mock_find_persistent_volumes.assert_not_called()
        mock_find_persistent_root_volumes.assert_not_called()

    @patch("osm_ng_ro.ns.Ns._sort_vdu_interfaces")
    @patch("osm_ng_ro.ns.Ns._partially_locate_vdu_interfaces")
    @patch("osm_ng_ro.ns.Ns._prepare_vdu_interfaces")
    @patch("osm_ng_ro.ns.Ns._prepare_vdu_cloud_init")
    @patch("osm_ng_ro.ns.Ns._prepare_vdu_ssh_keys")
    @patch("osm_ng_ro.ns.Ns.find_persistent_root_volumes")
    @patch("osm_ng_ro.ns.Ns.find_persistent_volumes")
    @patch("osm_ng_ro.ns.Ns._add_persistent_root_disk_to_disk_list")
    @patch("osm_ng_ro.ns.Ns._add_persistent_ordinary_disks_to_disk_list")
    @patch("osm_ng_ro.ns.Ns._prepare_vdu_affinity_group_list")
    def test_process_vdu_params_prepare_vdu_interfaces_raises_exception(
        self,
        mock_prepare_vdu_affinity_group_list,
        mock_add_persistent_ordinary_disks_to_disk_list,
        mock_add_persistent_root_disk_to_disk_list,
        mock_find_persistent_volumes,
        mock_find_persistent_root_volumes,
        mock_prepare_vdu_ssh_keys,
        mock_prepare_vdu_cloud_init,
        mock_prepare_vdu_interfaces,
        mock_locate_vdu_interfaces,
        mock_sort_vdu_interfaces,
    ):
        """Prepare vdu interfaces method raises exception."""
        target_vdu = deepcopy(target_vdu_wth_persistent_storage)

        self.maxDiff = None
        target_vdu["interfaces"] = interfaces_wthout_positions
        mock_prepare_vdu_cloud_init.return_value = {}
        mock_prepare_vdu_affinity_group_list.return_value = []
        persistent_root_disk = {
            "persistent-root-volume": {
                "image_id": "ubuntu20.04",
                "size": "10",
                "keep": True,
            }
        }
        mock_find_persistent_root_volumes.return_value = persistent_root_disk
        new_kwargs = deepcopy(kwargs)
        new_kwargs.update(
            {
                "vnfr_id": vnfr_id,
                "nsr_id": nsr_id,
                "tasks_by_target_record_id": {},
                "logger": "logger",
            }
        )
        mock_prepare_vdu_interfaces.side_effect = TypeError

        vnfd = deepcopy(vnfd_wth_persistent_storage)
        db.get_one.return_value = vnfd
        with self.assertRaises(Exception) as err:
            Ns._process_vdu_params(
                target_vdu, indata, vim_info=None, target_record_id=None, **new_kwargs
            )
            self.assertEqual(type(err), TypeError)
        mock_sort_vdu_interfaces.assert_not_called()
        mock_locate_vdu_interfaces.assert_called_once_with(target_vdu)
        mock_prepare_vdu_cloud_init.assert_not_called()
        mock_add_persistent_root_disk_to_disk_list.assert_not_called()
        mock_add_persistent_ordinary_disks_to_disk_list.assert_not_called()
        mock_prepare_vdu_interfaces.assert_called_once()
        mock_prepare_vdu_ssh_keys.assert_not_called()
        mock_prepare_vdu_affinity_group_list.assert_not_called()
        mock_find_persistent_volumes.assert_not_called()
        mock_find_persistent_root_volumes.assert_not_called()

    @patch("osm_ng_ro.ns.Ns._sort_vdu_interfaces")
    @patch("osm_ng_ro.ns.Ns._partially_locate_vdu_interfaces")
    @patch("osm_ng_ro.ns.Ns._prepare_vdu_interfaces")
    @patch("osm_ng_ro.ns.Ns._prepare_vdu_cloud_init")
    @patch("osm_ng_ro.ns.Ns._prepare_vdu_ssh_keys")
    @patch("osm_ng_ro.ns.Ns.find_persistent_root_volumes")
    @patch("osm_ng_ro.ns.Ns.find_persistent_volumes")
    @patch("osm_ng_ro.ns.Ns._add_persistent_root_disk_to_disk_list")
    @patch("osm_ng_ro.ns.Ns._add_persistent_ordinary_disks_to_disk_list")
    @patch("osm_ng_ro.ns.Ns._prepare_vdu_affinity_group_list")
    def test_process_vdu_params_add_persistent_root_disk_raises_exception(
        self,
        mock_prepare_vdu_affinity_group_list,
        mock_add_persistent_ordinary_disks_to_disk_list,
        mock_add_persistent_root_disk_to_disk_list,
        mock_find_persistent_volumes,
        mock_find_persistent_root_volumes,
        mock_prepare_vdu_ssh_keys,
        mock_prepare_vdu_cloud_init,
        mock_prepare_vdu_interfaces,
        mock_locate_vdu_interfaces,
        mock_sort_vdu_interfaces,
    ):
        """Add persistent root disk method raises exception."""
        target_vdu = deepcopy(target_vdu_wth_persistent_storage)

        self.maxDiff = None
        target_vdu["interfaces"] = interfaces_wthout_positions
        mock_prepare_vdu_cloud_init.return_value = {}
        mock_prepare_vdu_affinity_group_list.return_value = []
        mock_add_persistent_root_disk_to_disk_list.side_effect = KeyError
        new_kwargs = deepcopy(kwargs)
        new_kwargs.update(
            {
                "vnfr_id": vnfr_id,
                "nsr_id": nsr_id,
                "tasks_by_target_record_id": {},
                "logger": "logger",
            }
        )

        vnfd = deepcopy(vnfd_wth_persistent_storage)
        db.get_one.return_value = vnfd
        with self.assertRaises(Exception) as err:
            Ns._process_vdu_params(
                target_vdu, indata, vim_info=None, target_record_id=None, **new_kwargs
            )
            self.assertEqual(type(err), KeyError)
        mock_sort_vdu_interfaces.assert_not_called()
        mock_locate_vdu_interfaces.assert_called_once_with(target_vdu)
        mock_prepare_vdu_cloud_init.assert_called_once()
        mock_add_persistent_root_disk_to_disk_list.assert_called_once()
        mock_add_persistent_ordinary_disks_to_disk_list.assert_not_called()
        mock_prepare_vdu_interfaces.assert_called_once_with(
            target_vdu,
            {
                "depends_on": [
                    f"{ns_preffix}:image.0",
                    f"{ns_preffix}:flavor.0",
                ]
            },
            ns_preffix,
            vnf_preffix,
            "logger",
            {},
            [],
        )

        mock_prepare_vdu_ssh_keys.assert_called_once_with(target_vdu, None, {})
        mock_prepare_vdu_affinity_group_list.assert_not_called()
        mock_find_persistent_volumes.assert_not_called()
        mock_find_persistent_root_volumes.assert_not_called()

    def test_select_persistent_root_disk(self):
        vdu = deepcopy(target_vdu_wth_persistent_storage)
        vdu["virtual-storage-desc"] = [
            "persistent-root-volume",
            "persistent-volume2",
            "ephemeral-volume",
        ]
        vsd = deepcopy(vnfd_wth_persistent_storage)["virtual-storage-desc"][1]
        expected_result = vsd
        result = Ns._select_persistent_root_disk(vsd, vdu)
        self.assertEqual(result, expected_result)

    def test_select_persistent_root_disk_first_vsd_is_different(self):
        """VDU first virtual-storage-desc is different than vsd id."""
        vdu = deepcopy(target_vdu_wth_persistent_storage)
        vdu["virtual-storage-desc"] = [
            "persistent-volume2",
            "persistent-root-volume",
            "ephemeral-volume",
        ]
        vsd = deepcopy(vnfd_wth_persistent_storage)["virtual-storage-desc"][1]
        expected_result = None
        result = Ns._select_persistent_root_disk(vsd, vdu)
        self.assertEqual(result, expected_result)

    def test_select_persistent_root_disk_vsd_is_not_persistent(self):
        """vsd type is not persistent."""
        vdu = deepcopy(target_vdu_wth_persistent_storage)
        vdu["virtual-storage-desc"] = [
            "persistent-volume2",
            "persistent-root-volume",
            "ephemeral-volume",
        ]
        vsd = deepcopy(vnfd_wth_persistent_storage)["virtual-storage-desc"][1]
        vsd["type-of-storage"] = "etsi-nfv-descriptors:ephemeral-storage"
        expected_result = None
        result = Ns._select_persistent_root_disk(vsd, vdu)
        self.assertEqual(result, expected_result)

    def test_select_persistent_root_disk_vsd_does_not_have_size(self):
        """vsd size is None."""
        vdu = deepcopy(target_vdu_wth_persistent_storage)
        vdu["virtual-storage-desc"] = [
            "persistent-volume2",
            "persistent-root-volume",
            "ephemeral-volume",
        ]
        vsd = deepcopy(vnfd_wth_persistent_storage)["virtual-storage-desc"][1]
        vsd["size-of-storage"] = None
        expected_result = None
        result = Ns._select_persistent_root_disk(vsd, vdu)
        self.assertEqual(result, expected_result)

    def test_select_persistent_root_disk_vdu_wthout_vsd(self):
        """VDU does not have virtual-storage-desc."""
        vdu = deepcopy(target_vdu_wth_persistent_storage)
        vsd = deepcopy(vnfd_wth_persistent_storage)["virtual-storage-desc"][1]
        expected_result = None
        result = Ns._select_persistent_root_disk(vsd, vdu)
        self.assertEqual(result, expected_result)

    def test_select_persistent_root_disk_invalid_vsd_type(self):
        """vsd is list, expected to be a dict."""
        vdu = deepcopy(target_vdu_wth_persistent_storage)
        vsd = deepcopy(vnfd_wth_persistent_storage)["virtual-storage-desc"]
        with self.assertRaises(AttributeError):
            Ns._select_persistent_root_disk(vsd, vdu)


class TestSFC(unittest.TestCase):
    def setUp(self):
        self.ns = Ns()
        self.logger = CopyingMock(autospec=True)

    @patch("osm_ng_ro.ns.Ns._prefix_ip_address")
    @patch("osm_ng_ro.ns.Ns._process_ip_proto")
    @patch("osm_ng_ro.ns.Ns._get_vnfr_vdur_text")
    def test_process_classification_params(
        self, mock_get_vnfr_vdur_text, mock_process_ip_proto, mock_prefix_ip_address
    ):
        db = Mock()
        mock_prefix_ip_address.side_effect = ["10.10.10.10/32", "20.20.20.20/32"]
        mock_process_ip_proto.return_value = "tcp"
        mock_get_vnfr_vdur_text.return_value = "vdur_text"
        vim_info, indata, target_record_id = {}, {}, ""
        target_classification = {
            "vnfr_id": "1234",
            "source-ip-address": "10.10.10.10",
            "destination-ip-address": "20.20.20.20",
            "ip-proto": "6",
            "id": "rule1",
            "source-port": "0",
            "destination-port": 5555,
            "vdur_id": "5678",
            "ingress_port_index": 0,
            "vim_info": vim_info,
        }
        kwargs = {"db": db}

        expected_result = {
            "depends_on": ["vdur_text"],
            "params": {
                "destination_ip_prefix": "20.20.20.20/32",
                "destination_port_range_max": 5555,
                "destination_port_range_min": 5555,
                "logical_source_port": "TASK-vdur_text",
                "logical_source_port_index": 0,
                "name": "rule1",
                "protocol": "tcp",
                "source_ip_prefix": "10.10.10.10/32",
                "source_port_range_max": "0",
                "source_port_range_min": "0",
            },
        }

        result = self.ns._process_classification_params(
            target_classification, indata, vim_info, target_record_id, **kwargs
        )
        self.assertEqual(expected_result, result)

    def test_process_sfp_params(self):
        sf_text = "nsrs:1234:sf.sf1"
        classi_text = "nsrs:1234:classification.rule1"
        vim_info, indata, target_record_id = {}, {}, ""
        target_sfp = {
            "id": "sfp1",
            "sfs": ["sf1"],
            "classifications": ["rule1"],
            "vim_info": vim_info,
        }

        kwargs = {"nsr_id": "1234"}

        expected_result = {
            "depends_on": [sf_text, classi_text],
            "params": {
                "name": "sfp1",
                "sfs": ["TASK-" + sf_text],
                "classifications": ["TASK-" + classi_text],
            },
        }

        result = self.ns._process_sfp_params(
            target_sfp, indata, vim_info, target_record_id, **kwargs
        )
        self.assertEqual(expected_result, result)

    def test_process_sf_params(self):
        sfi_text = "nsrs::sfi.sfi1"
        vim_info, indata, target_record_id = {}, {}, ""
        target_sf = {"id": "sf1", "sfis": ["sfi1"], "vim_info": vim_info}

        kwargs = {"ns_id": "1234"}

        expected_result = {
            "depends_on": [sfi_text],
            "params": {
                "name": "sf1",
                "sfis": ["TASK-" + sfi_text],
            },
        }

        result = self.ns._process_sf_params(
            target_sf, indata, vim_info, target_record_id, **kwargs
        )
        self.assertEqual(expected_result, result)

    @patch("osm_ng_ro.ns.Ns._get_vnfr_vdur_text")
    def test_process_sfi_params(self, mock_get_vnfr_vdur_text):
        db = Mock()
        mock_get_vnfr_vdur_text.return_value = "vdur_text"
        vim_info, indata, target_record_id = {}, {}, ""
        target_sfi = {
            "id": "sfi1",
            "ingress_port": "vnf-cp0-ext",
            "egress_port": "vnf-cp0-ext",
            "vnfr_id": "1234",
            "vdur_id": "5678",
            "ingress_port_index": 0,
            "egress_port_index": 0,
            "vim_info": {},
        }
        kwargs = {"db": db}

        expected_result = {
            "depends_on": ["vdur_text"],
            "params": {
                "name": "sfi1",
                "ingress_port": "TASK-vdur_text",
                "egress_port": "TASK-vdur_text",
                "ingress_port_index": 0,
                "egress_port_index": 0,
            },
        }

        result = self.ns._process_sfi_params(
            target_sfi, indata, vim_info, target_record_id, **kwargs
        )
        self.assertEqual(expected_result, result)

    def test_process_vnfgd_sfp(self):
        sfp = {
            "id": "sfp1",
            "position-desc-id": [
                {
                    "id": "position1",
                    "cp-profile-id": [{"id": "sf1"}],
                    "match-attributes": [{"id": "rule1"}],
                }
            ],
        }
        expected_result = {"id": "sfp1", "sfs": ["sf1"], "classifications": ["rule1"]}

        result = self.ns._process_vnfgd_sfp(sfp)
        self.assertEqual(expected_result, result)

    def test_process_vnfgd_sf(self):
        sf = {"id": "sf1", "constituent-profile-elements": [{"id": "sfi1", "order": 0}]}
        expected_result = {"id": "sf1", "sfis": ["sfi1"]}

        result = self.ns._process_vnfgd_sf(sf)
        self.assertEqual(expected_result, result)

    def test_process_vnfgd_sfi(self):
        sfi = {
            "id": "sfi1",
            "constituent-base-element-id": "vnf",
            "order": 0,
            "ingress-constituent-cpd-id": "vnf-cp0-ext",
            "egress-constituent-cpd-id": "vnf-cp0-ext",
        }
        db_vnfrs = {
            "1234": {
                "id": "1234",
                "member-vnf-index-ref": "vnf",
                "connection-point": [
                    {
                        "name": "vnf-cp0-ext",
                        "connection-point-id": "vdu-eth0-int",
                        "connection-point-vdu-id": "5678",
                        "id": "vnf-cp0-ext",
                    }
                ],
            }
        }
        expected_result = {
            "id": "sfi1",
            "ingress_port": "vnf-cp0-ext",
            "egress_port": "vnf-cp0-ext",
            "vnfr_id": "1234",
            "vdur_id": "5678",
            "ingress_port_index": 0,
            "egress_port_index": 0,
        }

        result = self.ns._process_vnfgd_sfi(sfi, db_vnfrs)
        self.assertEqual(expected_result, result)

    def test_process_vnfgd_classification(self):
        classification = {
            "id": "rule1",
            "ip-proto": 6,
            "source-ip-address": "10.10.10.10",
            "destination-ip-address": "20.20.20.20",
            "constituent-base-element-id": "vnf",
            "constituent-cpd-id": "vnf-cp0-ext",
            "destination-port": 5555,
        }
        db_vnfrs = {
            "1234": {
                "id": "1234",
                "member-vnf-index-ref": "vnf",
                "connection-point": [
                    {
                        "name": "vnf-cp0-ext",
                        "connection-point-id": "vdu-eth0-int",
                        "connection-point-vdu-id": "5678",
                        "id": "vnf-cp0-ext",
                    }
                ],
            }
        }

        expected_result = {
            "id": "rule1",
            "ip-proto": 6,
            "source-ip-address": "10.10.10.10",
            "destination-ip-address": "20.20.20.20",
            "destination-port": 5555,
            "vnfr_id": "1234",
            "vdur_id": "5678",
            "ingress_port_index": 0,
            "constituent-base-element-id": "vnf",
            "constituent-cpd-id": "vnf-cp0-ext",
        }

        result = self.ns._process_vnfgd_classification(classification, db_vnfrs)
        self.assertEqual(expected_result, result)
