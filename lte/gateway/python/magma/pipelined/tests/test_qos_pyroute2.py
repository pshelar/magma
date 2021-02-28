from pyroute2 import IPRoute
from pyroute2 import NetlinkError
from pyroute2 import protocols

import unittest
import socket
import logging
import traceback
import time
import pprint
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
        err = self.create_htb(iface, qid, max_bw, rate, parent_qid)
        if err:
            return err
        err = self.create_filter(iface, qid, qid, proto)
        if err:
            return err
        return 0

    def delete(self, iface: str, qid: str, proto=PROTOCOL) -> int:
        err = self.del_filter(iface, qid, qid, proto)
        if err:
            return err

        err = self.del_htb(iface, qid)
        if err:
            return err

        return 0

    def create_htb(self, iface: str, qid: str, max_bw: int, rate=None,
                    parent_qid: str = None) -> int:

        try:
            if_index = self._get_if_index(iface)
            htb_queue = QUEUE_PREFIX + qid
            ret = self._ipr.tc("add-class", "htb", if_index,
                               htb_queue, parent=parent_qid,
                               rate=rate, ceil=max_bw, prio=1)
            LOG.debug("Return: %s", ret)
        except (ValueError, NetlinkError) as ex:
            LOG.error("create-htb error : %s", ex.code)
            return ex.code
        return 0


    def del_htb(self, iface: str, qid: str) -> int:
        try:
            if_index = self._get_if_index(iface)
            htb_queue = QUEUE_PREFIX + qid

            err = self._ipr.tc("del-class", "htb", if_index, htb_queue)
        except (ValueError, NetlinkError) as ex:
            LOG.error("del-htb  error error : %s", ex.code)
            return ex.code
        return 0

    def create_filter(self, iface: str, mark: str, qid: str, proto: int = PROTOCOL) -> int:
        try:
            if_index = self._get_if_index(iface)

            class_id = int(0x10000) | int(qid, 16)
            self._ipr.tc("add-filter", "fw", if_index, int(mark, 16),
                         parent=0x10000,
                         prio=10,
                         protocol=proto,
                        classid=class_id)
        except (ValueError, NetlinkError) as ex:
            LOG.error("create-filter error : %s", ex.code)
            return ex.code
        return 0

    def del_filter(self, iface: str, mark: str, qid: str, proto: int) -> int:
        try:
            if_index = self._get_if_index(iface)

            class_id = int(0x10000) | int(qid, 16)

            self._ipr.tc("del-filter", "fw", if_index, int(mark, 16),
                         parent=0x10000,
                         prio=10,
                         protocol=proto,
                         classid=class_id)
        except (ValueError, NetlinkError) as ex:
            LOG.error("del-filter error : %s", ex.code)
            return ex.code
        return 0

    def _get_if_index(self, iface: str):
        if_index = self._iface_if_index.get(iface, -1)
        if if_index == -1:
            if_index = self._ipr.link_lookup(ifname=iface)
            self._iface_if_index[iface] = if_index

        return if_index

    def _print_classes(self, iface):
        if_index = self._get_if_index(iface)

        pprint.pprint(self._ipr.get_classes(if_index))

    def _print_filters(self, iface):
        if_index = self._get_if_index(iface)

        pprint.pprint(self._ipr.get_filters(if_index))


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
        BridgeTools.destroy_bridge(cls.BRIDGE)
        pass

    def check_qid_in_tc(self, qid):
        cmd = "tc filter show dev dev_qos"
        exe_cmd = cmd.split(" ")
        output = subprocess.check_output(exe_cmd)
        found = False
        for ln in output.decode('utf-8').split("\n"):
            ln = ln.strip()
            if not ln:
                continue
            tokens = ln.split(" ")

            if len(tokens) > 10 and tokens[9] == qid:
                found = True

        return found

    def test_basic(self):
        cls = self.__class__
        t1 = tc_qos()
        iface = cls.IFACE
        qid = "0xae"
        max_bw = 10000
        rate = 1000
        parent_qid = '1:fffe'

        err1 = t1.create(iface, qid, max_bw, rate, parent_qid)
        self.assertTrue(self.check_qid_in_tc(qid))
        err = t1.delete(iface, qid)
        self.assertEqual(err, 0)
        self.assertEqual(err1, 0)

    def test_hierarchy(self):
        cls = self.__class__
        t1 = tc_qos()
        # First queue

        iface1 = cls.IFACE
        qid1 = "0xae"
        max_bw = 10000
        rate = 1000
        parent_qid1 = '1:fffe'

        err1 = t1.create(iface1, qid1, max_bw, rate, parent_qid1)
        self.assertTrue(self.check_qid_in_tc(qid1))

        # Second queue

        qid2 = "0x1ae"
        max_bw = 10000
        rate = 1000
        parent_qid2 = '1:' + qid1

        err1 = t1.create(iface1, qid2, max_bw, rate, parent_qid2)
        self.assertTrue(self.check_qid_in_tc(qid2))
        # t1._print_classes(iface1)
        # t1._print_filters(iface1)

        err = t1.delete(iface1, qid2)
        self.assertEqual(err, 0)

        err = t1.delete(iface1, qid1)
        self.assertEqual(err, 0)
        self.assertEqual(err1, 0)


if __name__ == "__main__":
    unittest.main()
