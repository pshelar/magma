#!/bin/bash
# Copyright 2021 The Magma Authors.

# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Setting up env variable, user and project path
MAGMA_USER="magma"
AGW_INSTALL_CONFIG="/etc/systemd/system/multi-user.target.wants/agw_installation.service"
AGW_SCRIPT_PATH="/root/agw_install_ubuntu.sh"
DEPLOY_PATH="/home/$MAGMA_USER/magma/lte/gateway/deploy"
SUCCESS_MESSAGE="ok"
NEED_REBOOT=0
WHOAMI=$(whoami)
MAGMA_VERSION="${MAGMA_VERSION:-v1.5}"
CLOUD_INSTALL="cloud"
GIT_URL="${GIT_URL:-https://github.com/magma/magma.git}"


echo "Checking if the script has been executed by root user"
if [ "$WHOAMI" != "root" ]; then
  echo "You're executing the script as $WHOAMI instead of root.. exiting"
  exit 1
fi

wget https://raw.githubusercontent.com/magma/magma/"$MAGMA_VERSION"/lte/gateway/deploy/agw_pre_check_ubuntu.sh
if [[ -f ./agw_pre_check_ubuntu.sh ]]; then
  chmod 644 agw_pre_check_ubuntu.sh && bash agw_pre_check_ubuntu.sh
  while true; do
      read -r "Do you accept those modifications and want to proceed with magma installation?(y/n)" yn
      case $yn in
          [Yy]* ) break;;
          [Nn]* ) exit;;
          * ) echo "Please answer yes or no.";;
      esac
  done
else
  echo "agw_pre_check_ubuntu.sh is not available in your version"
fi

echo "Checking if Ubuntu is installed"
if ! grep -q 'Ubuntu' /etc/issue; then
  echo "Ubuntu is not installed"
  exit 1
fi

echo "Making sure $MAGMA_USER user is sudoers"
if ! grep -q "$MAGMA_USER ALL=(ALL) NOPASSWD:ALL" /etc/sudoers; then
  apt install -y sudo
  adduser --disabled-password --gecos "" $MAGMA_USER
  adduser $MAGMA_USER sudo
  echo "$MAGMA_USER ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers
fi

echo "Need to check if both interfaces are named eth0 and eth1"
INTERFACES=$(ip -br a)
if [[ $1 != "$CLOUD_INSTALL" ]] && ( [[ ! $INTERFACES == *'eth0'*  ]] || [[ ! $INTERFACES == *'eth1'* ]] || ! grep -q 'GRUB_CMDLINE_LINUX="net.ifnames=0 biosdevname=0"' /etc/default/grub); then
  # changing intefaces name
  sed -i 's/GRUB_CMDLINE_LINUX=""/GRUB_CMDLINE_LINUX="net.ifnames=0 biosdevname=0"/g' /etc/default/grub
  sed -i 's/enp0s3/eth0/g' /etc/netplan/50-cloud-init.yaml
  # changing interface name
  grub-mkconfig -o /boot/grub/grub.cfg

  # interface config
  apt install ifupdown
  echo "auto eth0
  iface eth0 inet dhcp" > /etc/network/interfaces.d/eth0
  # configuring eth1
  echo "auto eth1
  iface eth1 inet static
  address 10.0.2.1
  netmask 255.255.255.0" > /etc/network/interfaces.d/eth1
  # name server config
  ln -sf /var/run/systemd/resolve/resolv.conf /etc/resolv.conf

  # get rid of netplan
  systemctl unmask networking
  systemctl enable networking

  apt-get --assume-yes purge nplan netplan.i

  # Setting REBOOT flag to 1 because we need to reload new interface and network services.
  NEED_REBOOT=1
else
  echo "Interfaces name are correct, let's check if network and DNS are up"
  while ! ping -c 1 -W 1 -I eth0 google.com; do
    echo "Network not ready yet"
    sleep 1
  done
fi

if [[ "${REPO_PROTO}" == 'https' ]]; then
    echo "Ensure HTTPS apt transport method is installed"
    apt install -y apt-transport-https
fi

if [ $NEED_REBOOT = 1 ]; then
  echo "Will reboot in a few seconds, loading a boot script in order to install magma"
  if [ ! -f "$AGW_SCRIPT_PATH" ]; then
      cp "$(realpath $0)" "${AGW_SCRIPT_PATH}"
  fi
  cat <<EOF > $AGW_INSTALL_CONFIG
[Unit]
Description=AGW Installation
After=network-online.target
Wants=network-online.target
[Service]
Environment=MAGMA_VERSION=${MAGMA_VERSION}
Environment=GIT_URL=${GIT_URL}
Environment=REPO_PROTO=${REPO_PROTO}
Environment=REPO_HOST=${REPO_HOST}
Environment=REPO_DIST=${REPO_DIST}
Environment=REPO_COMPONENT=${REPO_COMPONENT}
Environment=REPO_KEY=${REPO_KEY}
Environment=REPO_KEY_FINGERPRINT=${REPO_KEY_FINGERPRINT}
Type=oneshot
ExecStart=/bin/bash ${AGW_SCRIPT_PATH}
TimeoutStartSec=3800
TimeoutSec=3600
User=root
Group=root
[Install]
WantedBy=multi-user.target
EOF
  chmod 644 $AGW_INSTALL_CONFIG
  reboot
fi

echo "Making sure eth0 is connected to internet"
PING_RESULT=$(ping -c 1 -I eth0 8.8.8.8 > /dev/null 2>&1 && echo "$SUCCESS_MESSAGE")
if [ "$PING_RESULT" != "$SUCCESS_MESSAGE" ]; then
  echo "eth0 (enp1s0) is not connected to internet, please double check your plugged wires."
  exit 1
fi
echo "Checking if magma has been installed"
MAGMA_INSTALLED=$(apt-cache show magma >  /dev/null 2>&1 echo "$SUCCESS_MESSAGE")
if [ "$MAGMA_INSTALLED" != "$SUCCESS_MESSAGE" ]; then
  echo "Magma not installed, processing installation"
  apt-get update
  apt-get -y install curl make virtualenv zip rsync git software-properties-common python3-pip python-dev
  alias python=python3
  pip3 install ansible

  git clone "${GIT_URL}" /home/$MAGMA_USER/magma
  cd /home/$MAGMA_USER/magma || exit
  git checkout "$MAGMA_VERSION"

  echo "Generating localhost hostfile for Ansible"
  echo "[magma_deploy]
  127.0.0.1 ansible_connection=local" > $DEPLOY_PATH/agw_hosts

  # install magma and its dependencies including OVS.
  su - $MAGMA_USER -c "ansible-playbook -e \"MAGMA_ROOT='/home/$MAGMA_USER/magma' OUTPUT_DIR='/tmp'\" -i $DEPLOY_PATH/agw_hosts $DEPLOY_PATH/magma_deploy.yml"

  echo "Deleting boot script if it exists"
  if [ -f "$AGW_INSTALL_CONFIG" ]; then
    rm -rf $AGW_INSTALL_CONFIG
  fi
  rm -rf /home/$MAGMA_USER/build
  echo "AGW installation is done, make sure all services above are running correctly.. rebooting"
  reboot
else
  echo "Magma already installed, skipping.."
fi
