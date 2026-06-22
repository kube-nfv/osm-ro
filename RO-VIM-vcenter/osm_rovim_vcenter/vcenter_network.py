# -*- coding: utf-8 -*-
# Copyright 2025 Indra
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
"""
Utility class to get networks information in vcenter
"""
import logging

from osm_ro_plugin import vimconn
from osm_rovim_vcenter import vcenter_util as vcutil
from pyVmomi import vim

DISTRIBUTED_PORTGROUP_KEY_PREFIX = "vim.dvs.DistributedVirtualPortgroup:"


class VCenterNetworkUtil:
    """
    Helper class to deal with vcenter networks
    """

    def __init__(self, log_level=None):
        self.logger = logging.getLogger("ro.vim.vcenter.network")
        if log_level:
            self.logger.setLevel(getattr(logging, log_level))

    def get_dvs_list(self, session, dvs_names):
        """
        Obtains distributed switches with the provided distributed switches names
        """
        self.logger.debug("Get dvs for dvs_names: %s", dvs_names)
        dvs = []
        content = vcutil.get_vcenter_content(session)
        container = content.viewManager.CreateContainerView(
            content.rootFolder, [vim.DistributedVirtualSwitch], True
        )
        for dswitch in container.view:
            if dswitch.name in dvs_names:
                dvs.append(dswitch)
        return dvs

    def get_port_groups_by_dvs_name(self, session, dvs_names):
        """
        Obtains distributed port groups for the indicated distributed switches
        """
        self.logger.debug("Get port groups for dvs_names: %s", dvs_names)
        dport_groups = []
        content = vcutil.get_vcenter_content(session)
        container = content.viewManager.CreateContainerView(
            content.rootFolder, [vim.DistributedVirtualSwitch], True
        )
        for dswitch in container.view:
            if dswitch.name in dvs_names:
                for portgroup in dswitch.portgroup:
                    dport_groups.append(portgroup)
        return dport_groups

    def find_port_group_by_name_dvs(self, session, dvs, port_group_name):
        """
        Obtains the distributed port group with the provided name searching in the distributed
        virtual switch dvs
        """
        port_group = None

        for pg in dvs.portgroup:
            if pg.name == port_group_name:
                port_group = pg

        if not port_group:
            raise vimconn.VimConnNotFoundException(
                f"Distributed port group with name: {port_group_name} not found"
            )

        return port_group

    def get_network_by_id(self, session, net_id):
        """
        Obtains a pyvmomi network instance object by id
        Currently only obtains distributed port group
        """
        if net_id.startswith(DISTRIBUTED_PORTGROUP_KEY_PREFIX):
            pg_key = net_id.removeprefix(DISTRIBUTED_PORTGROUP_KEY_PREFIX)
            pg = self._get_portgroup_by_key(session, pg_key)
            return pg
        else:
            self.logger.error(
                "Network: %s is not a distributed port group, currently not supported",
                net_id,
            )
            raise vimconn.VimConnNotFoundException(
                f"Network: {net_id} is not a distributed port group, currently not supported"
            )

    def get_vim_network_by_id(self, session, net_id):
        """
        Obtains a vim network from vim_id
        """
        if net_id.startswith(DISTRIBUTED_PORTGROUP_KEY_PREFIX):
            pg_key = net_id.removeprefix(DISTRIBUTED_PORTGROUP_KEY_PREFIX)
            pg = self._get_portgroup_by_key(session, pg_key)
            return self.get_vim_network_from_pg(pg)
        else:
            self.logger.error(
                "Network: %s is not a distributed port group, currently not supported",
                net_id,
            )
            raise vimconn.VimConnNotFoundException(
                f"Network: {net_id} is not a distributed port group, currently not supported"
            )

    def _get_portgroup_by_key(self, session, key):
        """
        Obtains a distributed port group with the indicated key
        """
        port_group = None

        content = vcutil.get_vcenter_content(session)
        container = content.viewManager.CreateContainerView(
            content.rootFolder, [vim.dvs.DistributedVirtualPortgroup], True
        )
        for pg in container.view:
            if pg.key == key:
                port_group = pg
        if not port_group:
            raise vimconn.VimConnNotFoundException(
                f"Portgroup with key: {key} not found"
            )
        else:
            return port_group

    def get_vim_network_from_pg(self, portgroup):
        """
        Obtains a vim network object from a distributed port group
        """
        port_number = portgroup.config.numPorts
        binding_type = portgroup.config.type
        backing_type = portgroup.config.backingType

        # Get VLAN Information
        vlan_spec = portgroup.config.defaultPortConfig.vlan
        vlan_id = None
        if isinstance(vlan_spec, vim.dvs.VmwareDistributedVirtualSwitch.VlanIdSpec):
            vlan_id = vlan_spec.vlanId
        elif isinstance(
            vlan_spec, vim.dvs.VmwareDistributedVirtualSwitch.TrunkVlanSpec
        ):
            vlan_id = [(vlan.start, vlan.end) for vlan in vlan_spec.vlanId]

        vim_network = {
            "id": DISTRIBUTED_PORTGROUP_KEY_PREFIX + portgroup.key,
            "name": portgroup.name,
            # There is no functionaly in vcenter to check if a network is active
            "port_number": port_number,
            "binding_type": binding_type,
            "vlan_id": vlan_id,
            "net_backing_type": backing_type,
        }
        return vim_network

    def get_dvs(self, session, dvs_name):
        """
        Obtains a distributed virtual switch using its name
        """
        dvs = vcutil.get_vcenter_obj(session, [vim.DistributedVirtualSwitch], dvs_name)
        if not dvs:
            raise vimconn.VimConnNotFoundException(
                f"Distributed virtual switch with name: {dvs_name} not found"
            )
        return dvs

    def create_distributed_port_group(
        self, session, port_group_name, dvs_name, vlan=None
    ):
        """
        Creates a distributed port group with name port_group_name in the
        distributed_virtual_switch named dvs_name
        """
        try:
            # Obtain dvs with name dvs_name
            dvs = self.get_dvs(session, dvs_name)

            # Create portgroup
            port_group_spec = vim.dvs.DistributedVirtualPortgroup.ConfigSpec()
            port_group_spec.name = port_group_name
            port_group_spec.type = (
                vim.dvs.DistributedVirtualPortgroup.PortgroupType.earlyBinding
            )

            if vlan:
                vlan_spec = vim.dvs.VmwareDistributedVirtualSwitch.VlanIdSpec()
                vlan_spec.vlanId = vlan
                vlan_spec.inherited = False  # Ensure it's explicitly set
                port_group_spec.defaultPortConfig = (
                    vim.dvs.VmwareDistributedVirtualSwitch.VmwarePortConfigPolicy()
                )
                port_group_spec.defaultPortConfig.vlan = vlan_spec

            task = dvs.AddDVPortgroup_Task([port_group_spec])
            vcutil.wait_for_task(task)
            self.logger.debug(
                "Distributed port group with name: %s created", port_group_name
            )

            # Obtain portgroup created and return it
            port_group = self.find_port_group_by_name_dvs(session, dvs, port_group_name)
            net_key = DISTRIBUTED_PORTGROUP_KEY_PREFIX + port_group.key

            return net_key, port_group
        except vim.fault.DuplicateName as e:
            self.logger.error(
                f"Distributed port group with name: {port_group_name} already exists",
                exc_info=True,
            )
            raise vimconn.VimConnConflictException(
                f"Distributed port group with name: {port_group_name} already exists"
            ) from None

    def delete_distributed_port_group(self, port_group):
        """
        Deletes the indicated distributed port group
        """
        self.logger.debug("Delete distributed port group key: %s", port_group.key)
        task = port_group.Destroy_Task()
        vcutil.wait_for_task(task)
        self.logger.debug("Distributed port group deleted")

    def is_distributed_port_group(self, net_id):
        """
        Checks if the net with net_id is a distributed port group
        """
        if net_id.startswith(DISTRIBUTED_PORTGROUP_KEY_PREFIX):
            return True
        else:
            return False

    def get_distributed_port_connected_vms(self, port_group):
        """
        Obtains the vms connected to the provided distributed port group
        """
        vms = []
        for vm in port_group.vm:
            vms.append(vm)
        return vms

    def is_nsx_port_group(self, port_group):
        """
        Check if the distributed port group backing type is nsx
        """
        if port_group.config.backingType == "nsx":
            return True
        else:
            return False

    def _get_distributed_port_group(self, session, portgroup_key):
        portgroup = None
        content = vcutil.get_vcenter_content(session)
        container = content.viewManager.CreateContainerView(
            content.rootFolder, [vim.DistributedVirtualSwitch], True
        )
        for dswitch in container.view:
            for pg in dswitch.portgroup:
                if pg.key == portgroup_key:
                    portgroup = pg
            if portgroup:
                break

        if not portgroup:
            raise vimconn.VimConnNotFoundException(
                f"unable to find portgroup key: {portgroup_key}"
            )
