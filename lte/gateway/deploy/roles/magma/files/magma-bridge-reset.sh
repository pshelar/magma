#!/bin/bash
# Copyright 2021 The Magma Authors.

# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

KMOD_RELOAD=${1:-""}
FLOW_DUMP="$(mktemp)"
SGI_BR="uplink_br0"

#check DHCP client
DHCP_PID=$(pgrep -a 'dhclient' | grep $SGI_BR | awk '{print $1}')
if [[ -n $DHCP_PID ]];
then
  for pid in $DHCP_PID
  do
    kill "$pid"
  done
fi

# save flows
ovs-ofctl dump-flows --no-names --no-stats $SGI_BR | \
            sed -e '/NXST_FLOW/d' \
                -e '/OFPST_FLOW/d' \
                -e 's/\(idle\|hard\)_age=[^,]*,//g' > "$FLOW_DUMP"

# remove OVS objects
ovs-vsctl --all destroy Flow_Sample_Collector_Set

ifdown uplink_br0
ifdown gtp_br0
ifdown patch-up
if [[ "$KMOD_RELOAD" != '-y' ]];
then
  service openvswitch-switch restart
else
  /etc/init.d/openvswitch-switch  force-reload-kmod
fi

# create OVS objects
sleep 1
ifup uplink_br0
ifup gtp_br0
ifup patch-up
sleep 1

# restore OVS flows
ovs-ofctl del-flows $SGI_BR
ovs-ofctl add-flows $SGI_BR "$FLOW_DUMP"
rm "$FLOW_DUMP"

# start DHCP client if needed
if [[ -n $DHCP_PID ]];
then
  dhclient $SGI_BR &
fi
