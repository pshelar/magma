"""
Copyright 2021 The Magma Authors.

This source code is licensed under the BSD-style license found in the
LICENSE file in the root directory of this source tree.

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

from __future__ import absolute_import, division, print_function, \
    unicode_literals

from abc import ABC, abstractmethod



class TcOpsBase(ABC):
    @abstractmethod
    def create_htb(self, iface: str, qid: str, max_bw: int, rate=None,
                    parent_qid: str = None) -> int:
        ...

    @abstractmethod
    def del_htb(self, iface: str, qid: str) -> int:
        ...

    @abstractmethod
    def create_filter(self, iface: str, mark: str, qid: str, proto: int = 3) -> int:
        ...

    @abstractmethod
    def del_filter(self, iface: str, mark: str, qid: str, proto: int = 3) -> int:
        ...
