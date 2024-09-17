#
# Copyright 2020 University of Lancaster - High Performance Networks Research
# Group
# All Rights Reserved.
#
# Contributors: Will Fantom, Paul McCherry
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
# products derived from this software without specific prior written permission.
#
# This work has been performed in the context of DCMS UK 5G Testbeds
# & Trials Programme and in the framework of the Metro-Haul project -
# funded by the European Commission under Grant number 761727 through the
# Horizon 2020 and 5G-PPP programmes.
##

import json
import logging
import struct

from osm_ro_plugin.sdnconn import SdnConnectorBase, SdnConnectorError
import paramiko
import requests


class DpbSshInterface:
    """Communicate with the DPB via SSH"""

    __LOGGER_NAME_EXT = ".ssh"
    __FUNCTION_MAP_POS = 1

    def __init__(
        self, username, password, wim_url, wim_port, network, auth_data, logger_name
    ):
        self.logger = logging.getLogger(logger_name + self.__LOGGER_NAME_EXT)
        self.__username = username
        self.__password = password
        self.__url = wim_url
        self.__port = wim_port
        self.__network = network
        self.__auth_data = auth_data
        self.__session_id = 1
        self.__ssh_client = self.__create_client()
        self.__stdin = None
        self.__stdout = None
        self.logger.info("SSH connection to DPB defined")

    def _check_connection(self):
        if not (self.__stdin and self.__stdout):
            self.__stdin, self.__stdout = self.__connect()

    def post(self, function, url_params="", data=None, get_response=True):
        """post request to dpb via ssh

        notes:
        - session_id need only be unique per ssh session, thus is currently safe if
          ro is restarted
        """
        self._check_connection()

        if data is None:
            data = {}

        url_ext_info = url_params.split("/")

        for i in range(0, len(url_ext_info)):
            if url_ext_info[i] == "service":
                data["service-id"] = int(url_ext_info[i + 1])

        data["type"] = function[self.__FUNCTION_MAP_POS]
        data = {
            "session": self.__session_id,
            "content": data,
        }
        self.__session_id += 1

        try:
            data = json.dumps(data).encode("utf-8")
            data_packed = struct.pack(">I" + str(len(data)) + "s", len(data), data)
            self.__stdin.write(data_packed)
            self.logger.debug("Data sent to DPB via SSH")
        except Exception as e:
            raise SdnConnectorError("Failed to write via SSH | text: {}".format(e), 500)

        try:
            data_len = struct.unpack(">I", self.__stdout.read(4))[0]
            data = struct.unpack(str(data_len) + "s", self.__stdout.read(data_len))[0]

            return json.loads(data).get("content", {})
        except Exception as e:
            raise SdnConnectorError(
                "Could not get response from WIM | text: {}".format(e), 500
            )

    def get(self, function, url_params=""):
        raise SdnConnectorError("SSH Get not implemented", 500)

    def __create_client(self):
        ssh_client = paramiko.SSHClient()
        # Load known host keys
        ssh_client.load_system_host_keys()
        # Reject unknown hosts
        ssh_client.set_missing_host_key_policy(paramiko.RejectPolicy())

        return ssh_client

    def __connect(self):
        private_key = None
        password = None

        if self.__auth_data.get("auth_type", "PASS") == "KEY":
            private_key = self.__build_private_key_obj()

        if self.__auth_data.get("auth_type", "PASS") == "PASS":
            password = self.__password

        try:
            self.__ssh_client.connect(
                hostname=self.__url,
                port=self.__port,
                username=self.__username,
                password=password,
                pkey=private_key,
                look_for_keys=False,
                compress=False,
            )
            # TODO: sanitizing commands to be executed
            # Whitelist of allowed commands
            # valid_commands = ["command1", "command2", "command3"]
            # if self.__network not in valid_commands:
            #     raise SdnConnectorError("Invalid command executed", 400)
            stdin, stdout, stderr = self.__ssh_client.exec_command(
                command=self.__network
            )
        except paramiko.BadHostKeyException as e:
            raise SdnConnectorError(
                "Could not add SSH host key | text: {}".format(e), 500
            )
        except paramiko.AuthenticationException as e:
            raise SdnConnectorError(
                "Could not authorize SSH connection | text: {}".format(e), 400
            )
        except paramiko.SSHException as e:
            raise SdnConnectorError(
                "Could not establish the SSH connection | text: {}".format(e), 500
            )
        except Exception as e:
            raise SdnConnectorError(
                "Unknown error occurred when connecting via SSH | text: {}".format(e),
                500,
            )

        try:
            data_len = struct.unpack(">I", stdout.read(4))[0]
            data = json.loads(
                struct.unpack(str(data_len) + "s", stdout.read(data_len))[0]
            )
        except Exception as e:
            raise SdnConnectorError(
                "Failed to get response from DPB | text: {}".format(e), 500
            )

        if "error" in data:
            raise SdnConnectorError(data.get("msg", data.get("error", "ERROR")), 500)

        self.logger.info("SSH connection to DPB established OK")

        return stdin, stdout

    def __build_private_key_obj(self):
        try:
            with open(self.__auth_data.get("key_file"), "r") as key_file:
                if self.__auth_data.get("key_type") == "RSA":
                    return paramiko.RSAKey.from_private_key(
                        key_file, password=self.__auth_data.get("key_pass", None)
                    )
                elif self.__auth_data.get("key_type") == "ECDSA":
                    return paramiko.ECDSAKey.from_private_key(
                        key_file, password=self.__auth_data.get("key_pass", None)
                    )
                else:
                    raise SdnConnectorError("Key type not supported", 400)
        except Exception as e:
            raise SdnConnectorError(
                "Could not load private SSH key | text: {}".format(e), 500
            )


class DpbRestInterface:
    """Communicate with the DPB via the REST API"""

    __LOGGER_NAME_EXT = ".rest"
    __FUNCTION_MAP_POS = 0

    def __init__(self, wim_url, wim_port, network, logger_name):
        self.logger = logging.getLogger(logger_name + self.__LOGGER_NAME_EXT)
        self.__base_url = "http://{}:{}/network/{}".format(
            wim_url, str(wim_port), network
        )
        self.logger.info("REST defined OK")

    def post(self, function, url_params="", data=None, get_response=True):
        url = self.__base_url + url_params + "/" + function[self.__FUNCTION_MAP_POS]

        try:
            self.logger.info(data)
            response = requests.post(url, json=data)

            if response.status_code != 200:
                raise SdnConnectorError(
                    "REST request failed (status code: {})".format(response.status_code)
                )

            if get_response:
                return response.json()
        except Exception as e:
            raise SdnConnectorError("REST request failed | text: {}".format(e), 500)

    def get(self, function, url_params=""):
        url = self.__base_url + url_params + function[self.__FUNCTION_MAP_POS]

        try:
            return requests.get(url)
        except Exception as e:
            raise SdnConnectorError("REST request failed | text: {}".format(e), 500)


class DpbConnector(SdnConnectorBase):
    """Use the DPB to establish multipoint connections"""

    __LOGGER_NAME = "ro.sdn.dpb"
    __SUPPORTED_SERV_TYPES = ["ELAN (L2)", "ELINE (L2)"]
    __SUPPORTED_CONNECTION_TYPES = ["REST", "SSH"]
    __SUPPORTED_SSH_AUTH_TYPES = ["KEY", "PASS"]
    __SUPPORTED_SSH_KEY_TYPES = ["ECDSA", "RSA"]
    __STATUS_MAP = {"ACTIVE": "ACTIVE", "ACTIVATING": "BUILD", "FAILED": "ERROR"}
    __ACTIONS_MAP = {
        "CREATE": ("create-service", "new-service"),
        "DEFINE": ("define", "define-service"),
        "ACTIVATE": ("activate", "activate-service"),
        "RELEASE": ("release", "release-service"),
        "DEACTIVATE": ("deactivate", "deactivate-service"),
        "CHECK": ("await-status", "await-service-status"),
        "GET": ("services", "NOT IMPLEMENTED"),
        "RESET": ("reset", "NOT IMPLEMENTED"),
    }

    def __init__(self, wim, wim_account, config):
        self.logger = logging.getLogger(self.__LOGGER_NAME)

        self.__wim = wim
        self.__account = wim_account
        self.__config = config
        self.__cli_config = self.__account.pop("config", None)

        self.__url = self.__wim.get("wim_url", "")
        self.__password = self.__account.get("passwd", "")
        self.__username = self.__account.get("user", "")
        self.__network = self.__cli_config.get("network", "")
        self.__connection_type = self.__cli_config.get("connection_type", "REST")
        self.__port = self.__cli_config.get(
            "port", (80 if self.__connection_type == "REST" else 22)
        )
        self.__ssh_auth = self.__cli_config.get("ssh_auth", None)

        if self.__connection_type == "SSH":
            interface = DpbSshInterface(
                self.__username,
                self.__password,
                self.__url,
                self.__port,
                self.__network,
                self.__ssh_auth,
                self.__LOGGER_NAME,
            )
        elif self.__connection_type == "REST":
            interface = DpbRestInterface(
                self.__url, self.__port, self.__network, self.__LOGGER_NAME
            )
        else:
            raise SdnConnectorError(
                "Connection type not supported (must be SSH or REST)", 400
            )

        self.__post = interface.post
        self.__get = interface.get
        self.logger.info("DPB WimConn Init OK")

    def create_connectivity_service(self, service_type, connection_points, **kwargs):
        self.logger.info("Creating a connectivity service")

        try:
            response = self.__post(self.__ACTIONS_MAP.get("CREATE"))

            if "service-id" in response:
                service_id = int(response.get("service-id"))
                self.logger.debug("created service id {}".format(service_id))
            else:
                raise SdnConnectorError(
                    "Invalid create service response (could be an issue with the DPB)",
                    500,
                )

            data = {"segment": []}

            for point in connection_points:
                data["segment"].append(
                    {
                        "terminal-name": point.get("service_endpoint_id"),
                        "label": int(
                            (point.get("service_endpoint_encapsulation_info")).get(
                                "vlan"
                            )
                        ),
                        "ingress-bw": 10.0,
                        "egress-bw": 10.0,
                    }
                )
                # "ingress-bw": (bandwidth.get(point.get("service_endpoint_id"))).get("ingress"),
                # "egress-bw": (bandwidth.get(point.get("service_endpoint_id"))).get("egress")}

            self.__post(
                self.__ACTIONS_MAP.get("DEFINE"),
                "/service/" + str(service_id),
                data,
                get_response=False,
            )
            self.__post(
                self.__ACTIONS_MAP.get("ACTIVATE"),
                "/service/" + str(service_id),
                get_response=False,
            )
            self.logger.debug("Created connectivity service id:{}".format(service_id))

            return (str(service_id), None)
        except Exception as e:
            raise SdnConnectorError(
                "Connectivity service could not be made | text: {}".format(e), 500
            )

    def get_connectivity_service_status(self, service_uuid, conn_info=None):
        self.logger.info(
            "Checking connectivity service status id:{}".format(service_uuid)
        )
        data = {"timeout-millis": 10000, "acceptable": ["ACTIVE", "FAILED"]}

        try:
            response = self.__post(
                self.__ACTIONS_MAP.get("CHECK"),
                "/service/" + service_uuid,
                data,
            )

            if "status" in response:
                status = response.get("status", None)
                self.logger.info("CHECKED CONNECTIVITY SERVICE STATUS")

                return {"wim_status": self.__STATUS_MAP.get(status)}
            else:
                raise SdnConnectorError(
                    "Invalid status check response (could be an issue with the DPB)",
                    500,
                )
        except Exception as e:
            raise SdnConnectorError(
                "Failed to check service status | text: {}".format(e), 500
            )

    def delete_connectivity_service(self, service_uuid, conn_info=None):
        self.logger.info("Deleting connectivity service id: {}".format(service_uuid))

        try:
            self.__post(
                self.__ACTIONS_MAP.get("RELEASE"),
                "/service/" + service_uuid,
                get_response=False,
            )
        except Exception as e:
            raise SdnConnectorError(
                "Could not delete service id:{} (could be an issue with the DPB): {}".format(
                    service_uuid, e
                ),
                500,
            )

        self.logger.debug("Deleted connectivity service id:{}".format(service_uuid))

        return None

    def edit_connectivity_service(
        self, service_uuid, conn_info=None, connection_points=None, **kwargs
    ):
        self.logger.info("Editing connectivity service id: {}".format(service_uuid))
        data = {"timeout-millis": 10000, "acceptable": ["DORMANT"]}

        try:
            self.__post(
                self.__ACTIONS_MAP.get("RESET"),
                "/service/" + service_uuid,
                get_response=False,
            )
            response = self.__post(
                self.__ACTIONS_MAP.get("CHECK"),
                "/service/" + service_uuid,
                data,
            )

            if "status" in response:
                self.logger.debug("Connectivity service {} reset".format(service_uuid))
            else:
                raise SdnConnectorError(
                    "Invalid status check response (could be an issue with the DPB)",
                    500,
                )
        except Exception as e:
            raise SdnConnectorError("Failed to reset service | text: {}".format(e), 500)

        try:
            data = {"segment": []}

            for point in connection_points:
                data["segment"].append(
                    {
                        "terminal-name": point.get("service_endpoint_id"),
                        "label": int(
                            (point.get("service_endpoint_encapsulation_info")).get(
                                "vlan"
                            )
                        ),
                        "ingress-bw": 10.0,
                        "egress-bw": 10.0,
                    }
                )
                # "ingress-bw": (bandwidth.get(point.get("service_endpoint_id"))).get("ingress"),
                # "egress-bw": (bandwidth.get(point.get("service_endpoint_id"))).get("egress")}

            self.__post(
                self.__ACTIONS_MAP.get("DEFINE"),
                "/service/" + str(service_uuid),
                data,
                get_response=False,
            )
            self.__post(
                self.__ACTIONS_MAP.get("ACTIVATE"),
                "/service/" + str(service_uuid),
                get_response=False,
            )
        except Exception as e:
            raise SdnConnectorError(
                "Failed to edit connectivity service | text: {}".format(e), 500
            )

        self.logger.debug("Edited connectivity service {}".format(service_uuid))

        return conn_info

    def __check_service(self, serv_type, points, kwargs):
        if serv_type not in self.__SUPPORTED_SERV_TYPES:
            raise SdnConnectorError("Service type no supported", 400)
        # Future: BW Checks here
