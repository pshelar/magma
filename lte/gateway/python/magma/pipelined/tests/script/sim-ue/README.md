Setup OVS flow table using S1ap test. Once flow table is up stop services and follow the steps:

0. sudo /usr/share/openvswitch/scripts/ovs-save save-flows gtp_br0
1. sudo bash -x sim-ue.sh  s 1 192.168.128.72 0xa000128
2. sudo python http-serve.py&

Validate ping:
sudo ip netns exec ue_ns_1 ping 192.168.128.1

Validate http:
sudo ip netns exec ue_ns_1 curl   192.168.128.1:80/index

Destroy:
sudo bash -x sim-ue.sh  d 1
sudo bash -x envoy-service.sh destroy
