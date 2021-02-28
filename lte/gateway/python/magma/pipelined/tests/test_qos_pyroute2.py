from pyroute2 import IPRoute
from pyroute2 import NetlinkError
from pyroute2 import protocols

import unittest
import socket
import logging
import traceback
import time
import subprocess
from magma.pipelined.bridge_util import BridgeTools
from magma.pipelined.qos.qos_tc_impl import TrafficClass

LOG = logging.getLogger('pipelined.qos.tc_rtnl')

QUEUE_PREFIX = '1:'
PROTOCOL = 3
class tc_qos:
    """
    Create TC scheduler and corresponding filter
    """
    def __init__(self):
        self._ipr = IPRoute()
        self._iface_if_index = {}

    def create(self, iface: str, qid: str, max_bw: int, rate=None,
               parent_qid: str = None, proto=PROTOCOL) -> int:
        try:
            if_index = self._get_if_index(iface)
            htb_queue = QUEUE_PREFIX + qid

            self._create_htb(if_index, htb_queue, max_bw, rate, parent_qid)
            self._create_filter(if_index, qid, qid, proto)
        except ValueError as ex:
            LOG.error("error : %s", ex)
            traceback.print_exc()

            return ex.code
        except NetlinkError as ex:
            print(ex)
            traceback.print_exc()
            LOG.error("create error : %s", ex)
            return ex.code
        return 0

    def delete(self, iface: str, qid: str, max_bw: int, rate=None,
               parent_qid: str = None, proto=PROTOCOL) -> int:
        try:
            if_index = self._get_if_index(iface)
            htb_queue = QUEUE_PREFIX + qid

            self._del_filter(if_index, qid, qid, proto)

        except ValueError as ex:
            LOG.error("error : %s", ex)
            traceback.print_exc()

            return ex.code
        except NetlinkError as ex:
            LOG.error("delete filter error : %s", ex)
            traceback.print_exc()
            return ex.code

        try:
            if_index = self._get_if_index(iface)
            htb_queue = QUEUE_PREFIX + qid

            self._del_htb(if_index, htb_queue, max_bw, rate, parent_qid)

        except ValueError as ex:
            LOG.error("error : %s", ex)
            traceback.print_exc()

            return ex.code
        except NetlinkError as ex:
            LOG.error("delete class error : %s", ex)
            traceback.print_exc()
            return ex.code

        return 0

    def _create_htb(self, if_index: int, qid: str, max_bw: int, rate=None,
                    parent_qid: str = None) -> int:
        err = self._ipr.tc("add-class", "htb", if_index, qid, parent=parent_qid, rate=rate, ceil=max_bw, prio=1)

    def _del_htb(self, if_index: int, qid: str, max_bw: int, rate=None,
                 parent_qid: str = None) -> int:
        err = self._ipr.tc("del-class", "htb", if_index, qid, parent=parent_qid, rate=rate, ceil=max_bw, prio=1)

    def _create_filter(self, if_index: int, mark: str, qid: str, proto: int) -> int:
        print("mark: ", mark)
        class_id = int(0x10000) | int(qid, 16)
        print("class_id: ", hex(class_id))
        print("pbs: ", protocols.ETH_P_ALL)
        print("pbs: socket.AF_INET: {} {}".format(socket.AF_INET, type(socket.AF_INET)))

        self._ipr.tc("add-filter", "fw", if_index, int(mark, 16),
                     parent=0x10000,
                     prio=10,
                     protocol=proto,
                    classid=class_id)

    def _del_filter(self, if_index: int, mark: str, qid: str, proto: int) -> int:
        class_id = int(0x10000) | int(qid, 16)

        self._ipr.tc("del-filter", "fw", if_index, int(mark, 16),
                     parent=0x10000,
                     prio=10,
                     protocol=proto,
                     classid=class_id)

    def _get_if_index(self, iface: str):
        if_index = self._iface_if_index.get(iface, -1)
        if if_index == -1:
            if_index = self._ipr.link_lookup(ifname=iface)
            self._iface_if_index[iface] = if_index

        print("if_index {} -> {}".format(iface, if_index))
        return if_index


class TcSetypTest(unittest.TestCase):
    BRIDGE = 'testing_qos'
    IFACE = 'dev_qos'

    @classmethod
    def setUpClass(cls):
        BridgeTools.create_bridge(cls.BRIDGE, cls.BRIDGE)
        BridgeTools.create_internal_iface(cls.BRIDGE, cls.IFACE, None)
        TrafficClass.init_qdisc(cls.IFACE, True)

    @classmethod
    def tearDownClass(cls):
        # BridgeTools.destroy_bridge(cls.BRIDGE)
        pass

    def test_basic(self):
        cls = self.__class__
        t1 = tc_qos()
        iface = cls.IFACE
        qid = "0xae"
        max_bw = 10000
        rate = 1000
        parent_qid = '1:fffe'
        for i in range(1, 10):
            err1 = t1.create(iface, qid, max_bw, rate, parent_qid)
            # time.sleep(30)
            print("PROTOCOL : ", i)
            cmd = "tc filter show dev dev_qos"
            exe_cmd = cmd.split(" ")
            output = subprocess.check_output(exe_cmd)
            for ln in output.decode('utf-8').split("\n"):
                ln = ln.strip()
                if not ln:
                    continue
                print(ln)

            err = t1.delete(iface, qid, max_bw, rate, parent_qid)
            self.assertEqual(err, 0)
            self.assertEqual(err1, 0)


if __name__ == "__main__":
    unittest.main()
