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

import unittest
import warnings
from concurrent.futures import Future
from typing import List

from lte.protos.mconfig.mconfigs_pb2 import PipelineD
from lte.protos.mobilityd_pb2 import IPAddress

from magma.pipelined.app.he import HeaderEnrichmentController

from magma.pipelined.bridge_util import BridgeTools

from magma.pipelined.tests.app.start_pipelined import TestSetup, \
    PipelinedController
from magma.pipelined.tests.pipelined_test_util import start_ryu_app_thread, \
    stop_ryu_app_thread, create_service_manager, wait_after_send, \
    SnapshotVerifier
from magma.pipelined.policy_converters import convert_ip_str_to_ip_proto, \
    ipv4_address_to_str

from magma.pipelined.openflow.messages import MessageHub
from magma.pipelined.openflow.messages import MsgChannel
from magma.pipelined.app import he
from magma.pipelined.openflow.registers import Direction

test_he_ip_url_map = {}


def mocked_activate_he_urls_for_ue(ue_addr: IPAddress, urls: List[str], imsi: str, msisdn: str):
    ue_ip_str = ipv4_address_to_str(ue_addr)

    url_list = test_he_ip_url_map.get(ue_ip_str, [])
    url_list.extend(urls)
    test_he_ip_url_map[ue_ip_str] = url_list
    return True


def mocked_deactivate_he_urls_for_ue(ue_addr: IPAddress, urls: List[str]):
    ue_ip_str = ipv4_address_to_str(ue_addr)

    if ue_ip_str in test_he_ip_url_map:
        url_list = test_he_ip_url_map.get(ue_ip_str)
        if not urls:
            test_he_ip_url_map.pop(ue_ip_str)
            return

        for deleted in urls:
            if deleted in url_list:
                url_list.remove(deleted)
        if len(url_list) > 0:
            test_he_ip_url_map[ue_ip_str] = url_list
        else:
            test_he_ip_url_map.pop(ue_ip_str)


def _pkt_total(stats):
    return sum(n.packets for n in stats)


class HeTableTest(unittest.TestCase):
    BRIDGE = 'testing_br'
    IFACE = 'testing_br'
    MAC_DEST = "5e:cc:cc:b1:49:4b"
    BRIDGE_IP = '192.168.128.1'
    UE_BLOCK = '192.168.128.0/24'
    UE_MAC = '5e:cc:cc:b1:49:4b'
    UE_IP = '192.168.128.22'
    OTHER_MAC = '0a:00:27:00:00:02'
    OTHER_IP = '1.2.3.4'
    VETH = 'tveth'
    VETH_NS = 'tveth_ns'
    PROXY_PORT = '15'

    @classmethod
    @unittest.mock.patch('netifaces.ifaddresses',
                         return_value=[[{'addr': '00:11:22:33:44:55'}]])
    @unittest.mock.patch('netifaces.AF_LINK', 0)
    def setUpClass(cls, *_):
        """
        Starts the thread which launches ryu apps

        Create a testing bridge, add a port, setup the port interfaces. Then
        launch the ryu apps for testing pipelined. Gets the references
        to apps launched by using futures.
        """
        he.activate_he_urls_for_ue = mocked_activate_he_urls_for_ue
        he.deactivate_he_urls_for_ue = mocked_deactivate_he_urls_for_ue

        super(HeTableTest, cls).setUpClass()
        warnings.simplefilter('ignore')
        cls.service_manager = create_service_manager([], ['proxy'])
        cls._tbl_num = cls.service_manager.get_table_num(HeaderEnrichmentController.APP_NAME)

        BridgeTools.create_veth_pair(cls.VETH, cls.VETH_NS)
        BridgeTools.create_bridge(cls.BRIDGE, cls.IFACE)
        BridgeTools.add_ovs_port(cls.BRIDGE, cls.VETH, cls.PROXY_PORT)

        he_controller_reference = Future()
        testing_controller_reference = Future()

        test_setup = TestSetup(
            apps=[
                PipelinedController.HeaderEnrichment,
                PipelinedController.Testing,
                PipelinedController.StartupFlows
            ],
            references={
                PipelinedController.HeaderEnrichment:
                    he_controller_reference,
                PipelinedController.Testing:
                    testing_controller_reference,
                PipelinedController.StartupFlows:
                    Future(),
            },
            config={
                'setup_type': 'LTE',
                'bridge_name': cls.BRIDGE,
                'bridge_ip_address': cls.BRIDGE_IP,
                'uplink_port': 20,
                'proxy_port_name': cls.VETH,
                'clean_restart': True,
                'enable_nat': True,
                'ovs_gtp_port_number': 10,
            },
            mconfig=PipelineD(
                ue_ip_block=cls.UE_BLOCK,
            ),
            loop=None,
            service_manager=cls.service_manager,
            integ_test=False,
        )

        cls.thread = start_ryu_app_thread(test_setup)
        cls.he_controller = he_controller_reference.result()
        cls.testing_controller = testing_controller_reference.result()

    def _wait_for_responses(self, chan, response_count, logger):
        def fail(err):
            logger.error("Failed to install rule for subscriber: %s", err)

        for _ in range(response_count):
            try:
                result = chan.get()

            except MsgChannel.Timeout:
                return fail("No response from OVS policy mixin")
            if not result.ok():
                return fail(result.exception())

    @classmethod
    def tearDownClass(cls):
        stop_ryu_app_thread(cls.thread)
        BridgeTools.destroy_bridge(cls.BRIDGE)

    def tearDown(self):
        cls = self.__class__
        dp = HeTableTest.he_controller._datapath
        test_he_ip_url_map.clear()
        cls.he_controller.cleanup_on_disconnect(dp)

    def test_default_flows(self):
        """
        Verify that a proxy flows are setup
        """

        snapshot_verifier = SnapshotVerifier(self,
                                             self.BRIDGE,
                                             self.service_manager,
                                             max_sleep_time=20,
                                             datapath=HeTableTest.he_controller._datapath)

        with snapshot_verifier:
            pass

    def test_ue_flows_add(self):
        """
        Verify that a proxy flows are setup
        """
        cls = self.__class__
        self._msg_hub = MessageHub(HeTableTest.he_controller.logger)

        ue_ip = '1.1.1.1'
        tun_id = 1
        dest_server = '2.2.2.2'
        urls = ['abc0.com']
        flow_msg = cls.he_controller.get_subscriber_he_flows(Direction.OUT, ue_ip, tun_id, dest_server, 123,
                                                             urls, 'IMSI01', b'1')
        chan = self._msg_hub.send(flow_msg,
                                  HeTableTest.he_controller._datapath, )
        self._wait_for_responses(chan, len(flow_msg), HeTableTest.he_controller.logger)

        snapshot_verifier = SnapshotVerifier(self,
                                             self.BRIDGE,
                                             self.service_manager,
                                             max_sleep_time=20,
                                             datapath=HeTableTest.he_controller._datapath)

        with snapshot_verifier:
            pass
        self.assertEqual(test_he_ip_url_map[ue_ip], urls)

    def test_ue_flows_add_direction_in(self):
        """
        Verify that a proxy flows are setup
        """
        cls = self.__class__
        self._msg_hub = MessageHub(HeTableTest.he_controller.logger)

        ue_ip = '1.1.1.1'
        tun_id = 1
        dest_server = '2.2.2.2'
        flow_msg = cls.he_controller.get_subscriber_he_flows(Direction.IN, ue_ip, tun_id, dest_server, 123,
                                                             ['abc1.com'], 'IMSI01', b'1')
        chan = self._msg_hub.send(flow_msg,
                                  HeTableTest.he_controller._datapath, )
        self._wait_for_responses(chan, len(flow_msg), HeTableTest.he_controller.logger)

        snapshot_verifier = SnapshotVerifier(self,
                                             self.BRIDGE,
                                             self.service_manager,
                                             max_sleep_time=20,
                                             datapath=HeTableTest.he_controller._datapath)

        with snapshot_verifier:
            pass

    def test_ue_flows_add2(self):
        """
        Verify that a proxy flows are setup
        """
        cls = self.__class__
        self._msg_hub = MessageHub(HeTableTest.he_controller.logger)
        dp = HeTableTest.he_controller._datapath
        ue_ip1 = '1.1.1.200'
        tun_id1 = 1
        dest_server1 = '2.2.2.4'
        rule1 = 123

        flow_msg = cls.he_controller.get_subscriber_he_flows(Direction.OUT, ue_ip1, tun_id1, dest_server1, rule1,
                                                             ['abc2.com'], 'IMSI01', b'1')

        ue_ip2 = '10.10.10.20'
        tun_id2 = 2
        dest_server2 = '20.20.20.40'
        rule2 = 1230
        flow_msg.extend(cls.he_controller.get_subscriber_he_flows(Direction.OUT, ue_ip2, tun_id2, dest_server2, rule2,
                                                                  ['xyz2.com'], 'IMSI01', b'1'))
        chan = self._msg_hub.send(flow_msg, dp)
        self._wait_for_responses(chan, len(flow_msg), HeTableTest.he_controller.logger)

        snapshot_verifier = SnapshotVerifier(self,
                                             self.BRIDGE,
                                             self.service_manager,
                                             max_sleep_time=20,
                                             datapath=HeTableTest.he_controller._datapath)

        with snapshot_verifier:
            pass

    def test_ue_flows_del(self):
        """
        Verify that a proxy flows are setup
        """
        cls = self.__class__
        self._msg_hub = MessageHub(HeTableTest.he_controller.logger)
        dp = HeTableTest.he_controller._datapath
        ue_ip1 = '1.1.1.200'
        tun_id1 = 1

        dest_server1 = '2.2.2.4'
        rule1 = 123
        flow_msg = cls.he_controller.get_subscriber_he_flows(Direction.OUT, ue_ip1, tun_id1, dest_server1, rule1,
                                                             ['abc3.com'], 'IMSI01', b'1')

        ue_ip2 = '10.10.10.20'
        tun_id2 = 2
        dest_server2 = '20.20.20.40'
        rule2 = 1230
        flow_msg2 = cls.he_controller.get_subscriber_he_flows(Direction.OUT, ue_ip2, tun_id2, dest_server2, rule2,
                                                              ['abc3.com'], 'IMSI01', b'1')
        flow_msg.extend(flow_msg2)
        chan = self._msg_hub.send(flow_msg, dp)
        self._wait_for_responses(chan, len(flow_msg), HeTableTest.he_controller.logger)

        cls.he_controller.remove_subscriber_he_flows(convert_ip_str_to_ip_proto(ue_ip2), rule2)

        snapshot_verifier = SnapshotVerifier(self,
                                             self.BRIDGE,
                                             self.service_manager,
                                             max_sleep_time=20,
                                             datapath=HeTableTest.he_controller._datapath)

        with snapshot_verifier:
            pass

    def test_ue_flows_del2(self):
        """
        Verify that a proxy flows are setup
        """
        cls = self.__class__
        self._msg_hub = MessageHub(HeTableTest.he_controller.logger)
        dp = HeTableTest.he_controller._datapath
        ue_ip1 = '1.1.1.200'
        tun_id1 = 1
        dest_server1 = '2.2.2.4'
        rule1 = 123
        flow_msg = cls.he_controller.get_subscriber_he_flows(Direction.OUT, ue_ip1, tun_id1, dest_server1, rule1,
                                                             ['abc4.com'], 'IMSI01', b'1')

        ue_ip2 = '10.10.10.20'
        tun_id2 = 2
        dest_server2 = '20.20.20.40'
        rule2 = 1230
        flow_msg.extend(cls.he_controller.get_subscriber_he_flows(Direction.OUT, ue_ip2, tun_id2, dest_server2, rule2,
                                                                  ['abc4.com'], 'IMSI01', b'1'))

        ue_ip2 = '10.10.10.20'
        dest_server2 = '20.20.40.40'
        rule2 = 1230
        flow_msg.extend(cls.he_controller.get_subscriber_he_flows(Direction.OUT, ue_ip2, tun_id2, dest_server2, rule2,
                                                                  ['abc.com'], 'IMSI01', None))

        chan = self._msg_hub.send(flow_msg, dp)
        self._wait_for_responses(chan, len(flow_msg), HeTableTest.he_controller.logger)

        cls.he_controller.remove_subscriber_he_flows(convert_ip_str_to_ip_proto(ue_ip2))

        snapshot_verifier = SnapshotVerifier(self,
                                             self.BRIDGE,
                                             self.service_manager,
                                             max_sleep_time=20,
                                             datapath=HeTableTest.he_controller._datapath)

        with snapshot_verifier:
            pass
        # verify multiple remove works.
        cls.he_controller.remove_subscriber_he_flows(convert_ip_str_to_ip_proto(ue_ip2))

        self.assertEqual(test_he_ip_url_map.get(ue_ip1, None), ['abc4.com'])
        self.assertEqual(test_he_ip_url_map.get(ue_ip2, None), None)

    def test_ue_flows_urls(self):
        """
        Verify that a proxy flows are setup
        """
        cls = self.__class__
        self._msg_hub = MessageHub(HeTableTest.he_controller.logger)
        dp = HeTableTest.he_controller._datapath
        ue_ip1 = '1.1.1.200'
        tun_id1 = 1
        dest_server1 = '2.2.2.4'
        rule1 = 123
        flow_msg = cls.he_controller.get_subscriber_he_flows(Direction.OUT, ue_ip1, tun_id1, dest_server1, rule1,
                                                             ['abc5.com'], 'IMSI01', b'1')

        dest_server2 = '20.20.20.40'
        rule2 = 1230
        flow_msg.extend(cls.he_controller.get_subscriber_he_flows(Direction.OUT, ue_ip1, tun_id1, dest_server2, rule2,
                                                                  ['xyz5.com'], 'IMSI01', b'1'))

        self.assertEqual(test_he_ip_url_map.get(ue_ip1, None), ['abc5.com', 'xyz5.com'])


        chan = self._msg_hub.send(flow_msg, dp)
        self._wait_for_responses(chan, len(flow_msg), HeTableTest.he_controller.logger)

        snapshot_verifier = SnapshotVerifier(self,
                                             self.BRIDGE,
                                             self.service_manager,
                                             max_sleep_time=20,
                                             datapath=HeTableTest.he_controller._datapath)

        with snapshot_verifier:
            pass

        cls.he_controller.remove_subscriber_he_flows(convert_ip_str_to_ip_proto(ue_ip1), rule1)
        self.assertEqual(test_he_ip_url_map.get(ue_ip1, None), ['xyz5.com'])


if __name__ == "__main__":
    unittest.main()
