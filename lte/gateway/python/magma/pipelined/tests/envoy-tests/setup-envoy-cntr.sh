#!/bin/bash -ex

envoy_ns="envoy_ns"
conf="/home/vagrant/magma/lte/gateway/python/magma/pipelined/tests/envoy-tests/envoy-cntr.yaml"
bin="/usr/bin/envoy"

#/home/vagrant/magma/feg/gateway/services/envoy_controller/envoy_controller &
#sleep 5

bash -x ./t2.sh
sleep 1
$bin -c $conf -l debug&


