#!/bin/bash -ex

br=$1
uplink=$2
DHCP_PORT="t_dhcp0"

# setup bridge
ovs-vsctl --may-exist add-br "$br"
ovs-vsctl --may-exist add-port "$br" "$uplink"

#ovs-vsctl set Bridge "$br" fail_mode=secure

ovs-vsctl --may-exist add-port "$br" "$DHCP_PORT" -- set interface "$DHCP_PORT" type=internal
ifconfig "$DHCP_PORT"  up

logger "uplink bridge setup done"
