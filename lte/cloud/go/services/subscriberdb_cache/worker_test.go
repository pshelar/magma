/*
Copyright 2020 The Magma Authors.

This source code is licensed under the BSD-style license found in the
LICENSE file in the root directory of this source tree.

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package subscriberdb_cache_test

import (
	"strings"
	"testing"
	"time"

	"magma/lte/cloud/go/lte"
	lte_protos "magma/lte/cloud/go/protos"
	"magma/lte/cloud/go/serdes"
	lte_models "magma/lte/cloud/go/services/lte/obsidian/models"
	lte_test_init "magma/lte/cloud/go/services/lte/test_init"
	"magma/lte/cloud/go/services/subscriberdb"
	"magma/lte/cloud/go/services/subscriberdb/obsidian/models"
	"magma/lte/cloud/go/services/subscriberdb/storage"
	"magma/lte/cloud/go/services/subscriberdb_cache"
	"magma/orc8r/cloud/go/blobstore"
	"magma/orc8r/cloud/go/clock"
	"magma/orc8r/cloud/go/mproto"
	"magma/orc8r/cloud/go/services/configurator"
	configurator_test_init "magma/orc8r/cloud/go/services/configurator/test_init"
	"magma/orc8r/cloud/go/sqorc"
	"magma/orc8r/cloud/go/test_utils"
	"magma/orc8r/lib/go/protos"

	"github.com/stretchr/testify/assert"
)

func TestSubscriberdbCacheWorker(t *testing.T) {
	db, err := test_utils.GetSharedMemoryDB()
	assert.NoError(t, err)
	digestStore := storage.NewDigestStore(db, sqorc.GetSqlBuilder())
	assert.NoError(t, digestStore.Initialize())
	fact := blobstore.NewSQLBlobStorageFactory(subscriberdb.PerSubDigestTableBlobstore, db, sqorc.GetSqlBuilder())
	assert.NoError(t, fact.InitializeFactory())
	perSubDigestStore := storage.NewPerSubDigestStore(fact)
	serviceConfig := subscriberdb_cache.Config{
		SleepIntervalSecs:  5,
		UpdateIntervalSecs: 300,
	}

	lte_test_init.StartTestService(t)
	configurator_test_init.StartTestService(t)

	allNetworks, err := storage.GetAllNetworks(digestStore)
	assert.NoError(t, err)
	assert.Empty(t, allNetworks)
	digest, err := storage.GetDigest(digestStore, "n1")
	assert.NoError(t, err)
	assert.Empty(t, digest)
	perSubDigests, err := perSubDigestStore.GetDigest("n1")
	assert.NoError(t, err)
	assert.Empty(t, perSubDigests)

	err = configurator.CreateNetwork(configurator.Network{ID: "n1"}, serdes.Network)
	assert.NoError(t, err)

	_, _, err = subscriberdb_cache.RenewDigests(serviceConfig, digestStore, perSubDigestStore)
	assert.NoError(t, err)
	digest, err = storage.GetDigest(digestStore, "n1")
	assert.NoError(t, err)
	assert.NotEmpty(t, digest)
	perSubDigests, err = perSubDigestStore.GetDigest("n1")
	assert.NoError(t, err)
	assert.Empty(t, perSubDigests)
	digestExpected := digest

	// Detect outdated digests and update
	_, err = configurator.CreateEntities(
		"n1",
		[]configurator.NetworkEntity{
			{
				Type: lte.APNEntityType, Key: "apn1",
				Config: &lte_models.ApnConfiguration{},
			},
			{
				Type: lte.SubscriberEntityType, Key: "IMSI99999",
				Config: &models.SubscriberConfig{
					Lte: &models.LteSubscription{State: "ACTIVE"},
				},
			},
			{
				Type: lte.SubscriberEntityType, Key: "IMSI11111",
				Config: &models.SubscriberConfig{
					Lte: &models.LteSubscription{State: "ACTIVE"},
				},
			},
		},
		serdes.Entity,
	)
	assert.NoError(t, err)

	clock.SetAndFreezeClock(t, clock.Now().Add(10*time.Minute))
	_, _, err = subscriberdb_cache.RenewDigests(serviceConfig, digestStore, perSubDigestStore)
	assert.NoError(t, err)
	digest, err = storage.GetDigest(digestStore, "n1")
	assert.NoError(t, err)
	assert.NotEqual(t, digestExpected, digest)

	perSubDigests, err = perSubDigestStore.GetDigest("n1")
	assert.NoError(t, err)
	// The individual subscriber digests are ordered by subscriber ID, and are prefixed
	// by a hash of the subscriber data proto
	sub1 := &lte_protos.SubscriberData{
		Sid:        &lte_protos.SubscriberID{Id: "11111", Type: lte_protos.SubscriberID_IMSI},
		Lte:        &lte_protos.LTESubscription{State: lte_protos.LTESubscription_ACTIVE, AuthKey: []byte{}},
		Non_3Gpp:   &lte_protos.Non3GPPUserProfile{ApnConfig: []*lte_protos.APNConfiguration{}},
		NetworkId:  &protos.NetworkID{Id: "n1"},
		SubProfile: "default",
	}
	expectedDigestPrefix1, err := mproto.HashDeterministic(sub1)
	assert.NoError(t, err)
	assert.Equal(t, "11111", perSubDigests[0].Sid.Id)
	assert.NotEmpty(t, perSubDigests[0].Digest.GetMd5Base64Digest())
	assert.True(t, strings.HasPrefix(perSubDigests[0].Digest.GetMd5Base64Digest(), expectedDigestPrefix1))

	sub2 := &lte_protos.SubscriberData{
		Sid:        &lte_protos.SubscriberID{Id: "99999", Type: lte_protos.SubscriberID_IMSI},
		Lte:        &lte_protos.LTESubscription{State: lte_protos.LTESubscription_ACTIVE, AuthKey: []byte{}},
		Non_3Gpp:   &lte_protos.Non3GPPUserProfile{ApnConfig: []*lte_protos.APNConfiguration{}},
		NetworkId:  &protos.NetworkID{Id: "n1"},
		SubProfile: "default",
	}
	expectedDigestPrefix2, err := mproto.HashDeterministic(sub2)
	assert.NoError(t, err)
	assert.Equal(t, "99999", perSubDigests[1].Sid.Id)
	assert.NotEmpty(t, perSubDigests[1].Digest.GetMd5Base64Digest())
	assert.True(t, strings.HasPrefix(perSubDigests[1].Digest.GetMd5Base64Digest(), expectedDigestPrefix2))
	clock.UnfreezeClock(t)

	// Detect newly added and removed networks
	err = configurator.CreateNetwork(configurator.Network{ID: "n2"}, serdes.Network)
	assert.NoError(t, err)
	configurator.DeleteNetwork("n1")

	clock.SetAndFreezeClock(t, clock.Now().Add(20*time.Minute))
	_, _, err = subscriberdb_cache.RenewDigests(serviceConfig, digestStore, perSubDigestStore)
	assert.NoError(t, err)
	digest, err = storage.GetDigest(digestStore, "n1")
	assert.NoError(t, err)
	assert.Empty(t, digest)
	perSubDigests, err = perSubDigestStore.GetDigest("n1")
	assert.NoError(t, err)
	assert.Empty(t, perSubDigests)

	digest, err = storage.GetDigest(digestStore, "n2")
	assert.NoError(t, err)
	assert.NotEmpty(t, digest)
	perSubDigests, err = perSubDigestStore.GetDigest("n1")
	assert.NoError(t, err)
	assert.Empty(t, perSubDigests)

	allNetworks, err = storage.GetAllNetworks(digestStore)
	assert.NoError(t, err)
	assert.Equal(t, []string{"n2"}, allNetworks)
	clock.UnfreezeClock(t)
}
