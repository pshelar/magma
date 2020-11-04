"""
Copyright 2020 The Magma Authors.

This source code is licensed under the BSD-style license found in the
LICENSE file in the root directory of this source tree.

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
from collections import namedtuple
from typing import List

from ryu.lib.packet import ether_types
from ryu.lib.packet.in_proto import IPPROTO_TCP

from .base import MagmaController, ControllerType
from ryu.ofproto import ether
from magma.pipelined.openflow import flows
from magma.pipelined.imsi import encode_imsi
from magma.pipelined.openflow.magma_match import MagmaMatch
from magma.pipelined.openflow.registers import load_direction, Direction, \
    PASSTHROUGH_REG_VAL, TUN_PORT_REG, set_proxy_tag, reset_in_port
import logging

from ..bridge_util import BridgeTools

PROXY_PORT_NAME = 'proxy_port'
HTTP_PORT = 80
PROXY_TABLE = 'proxy'


class HeaderEnrichmentController(MagmaController):
    """
    A controller that tags related HTTP proxy flows.

        1. From UE to Proxy
        2. From Proxy to UE
        3. From Proxy to Upstream server
        4. From upstream server to Proxy

    This controller is also responsible for setting direction for traffic
    egressing proxy_port.

    load:0->NXM_OF_IN_PORT[]

    """

    APP_NAME = "proxy"
    APP_TYPE = ControllerType.PHYSICAL

    UplinkConfig = namedtuple(
        'heConfig',
        ['he_proxy_port',
         'he_enabled',
         'uplink_port'],
    )

    def __init__(self, *args, **kwargs):
        super(HeaderEnrichmentController, self).__init__(*args, **kwargs)

        self.tbl_num = self._service_manager.get_table_num(self.APP_NAME)

        self.next_table = \
            self._service_manager.get_next_table_num(self.APP_NAME)

        self._datapath = None
        self.config = self._get_config(kwargs['config'])

        self.logger.info("he app config: %s", self.config)

    def _get_config(self, config_dict) -> namedtuple:
        he_proxy_port = BridgeTools.get_ofport(config_dict.get('proxy_port_name'))

        he_enabled = config_dict.get('he_enabled', True)
        uplink_port = config_dict.get('uplink_port', None)

        return self.UplinkConfig(
            he_proxy_port=he_proxy_port,
            he_enabled=he_enabled,
            uplink_port=uplink_port)

    def initialize_on_connect(self, datapath):
        self._datapath = datapath
        self._install_default_flows(self._datapath)

    def cleanup_on_disconnect(self, datapath):
        """
        Cleanup flows on datapath disconnect event.

        Args:
            datapath: ryu datapath struct
        """
        if self._clean_restart:
            self.delete_all_flows(datapath)

    def delete_all_flows(self, datapath):
        flows.delete_all_flows_from_table(datapath, self.tbl_num)

    def _install_default_flows(self, dp):
        match = MagmaMatch(in_port=self.config.he_proxy_port)
        flows.add_drop_flow(dp, self.tbl_num, match,
                            priority=flows.MINIMUM_PRIORITY + 1)
        match = MagmaMatch()
        flows.add_resubmit_next_service_flow(dp, self.tbl_num, match,
                                             [],
                                             priority=flows.MINIMUM_PRIORITY,
                                             resubmit_table=self.next_table)

    def set_he_target_urls(self, ue_addr: str, ip_dst: str, urls: List[str], imsi: str,
                           msisdn: str):
        pass

    def get_subscriber_flows(self, ue_addr: str, ip_dst: str, urls: List[str],
                             imsi: str, msisdn: str):
        dp = self._datapath
        parser = dp.ofproto_parser

        # if urls is None:
        #     return []
        #
        # if ip_dst is None:
        #     logging.error("Missing dst ip, ignoring HE rule.")
        #     return []

        logging.info("got it")
        return []
        self.set_he_target_urls(ue_addr, ip_dst, urls, imsi, msisdn)

        msgs = []
        # 1.a. Going to UE: from uplink send to proxy
        match = MagmaMatch(in_port=self.config.uplink_port,
                           eth_type=ether_types.ETH_TYPE_IP,
                           ipv4_src=ip_dst,
                           ipv4_dst=ue_addr,
                           ip_proto=IPPROTO_TCP,
                           tcp_src=HTTP_PORT)
        actions = [load_direction(parser, Direction.IN), set_proxy_tag(parser)]
        msgs.append(
            flows.get_add_resubmit_current_service_flow_msg(dp, self.tbl_num,
                                                            match,
                                                            actions=actions,
                                                            priority=flows.DEFAULT_PRIORITY,
                                                            resubmit_table=self.next_table))

        # 1.b. Going to UE: from proxy send to UE
        match = MagmaMatch(in_port=self.config.he_proxy_port,
                           eth_type=ether_types.ETH_TYPE_IP,
                           ipv4_src=ip_dst,
                           ipv4_dst=ue_addr,
                           ip_proto=IPPROTO_TCP,
                           tcp_src=HTTP_PORT)
        actions = [reset_in_port(parser, self.config.uplink_port)]
        msgs.append(
            flows.get_add_resubmit_current_service_flow_msg(dp, self.tbl_num,
                                             match, actions=actions, priority=flows.DEFAULT_PRIORITY,
                                             resubmit_table=0))

        # 2.a. To internet from proxy port, send to UE
        match = MagmaMatch(in_port=self.config.he_proxy_port,
                           eth_type=ether_types.ETH_TYPE_IP,
                           ipv4_src=ue_addr,
                           ipv4_dst=ip_dst,
                           ip_proto=IPPROTO_TCP,
                           tcp_dst=HTTP_PORT)
        actions = [load_direction(parser, Direction.OUT)]
        msgs.append(
            flows.get_add_resubmit_current_service_flow_msg(dp, self.tbl_num,
                                             match, actions=actions, priority=flows.MEDIUM_PRIORITY,
                                             resubmit_table=self.next_table))

        # 2.b. To internet from ue send to proxy
        match = MagmaMatch(eth_type=ether_types.ETH_TYPE_IP,
                           ipv4_src=ue_addr,
                           ipv4_dst=ip_dst,
                           ip_proto=IPPROTO_TCP,
                           tcp_dst=HTTP_PORT)
        actions = [load_direction(parser, Direction.OUT), set_proxy_tag(parser)]
        msgs.append(
            flows.get_add_resubmit_current_service_flow_msg(dp, self.tbl_num,
                                             match, actions=actions, priority=flows.DEFAULT_PRIORITY,
                                             resubmit_table=self.next_table))
        return msgs

    def remove_subscriber_flow(self, ue_addr: str, ip_dst: str):
        pass
