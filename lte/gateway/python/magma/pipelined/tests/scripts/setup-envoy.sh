#!/bin/bash -ex

envoy_ns="envoy_ns"
conf="/home/vagrant/magma/lte/gateway/python/magma/pipelined/tests/scripts/envoy.yaml"
bin="/usr/bin/envoy"

bash -x ./t2.sh
sleep 1
$bin -c $conf -l debug
