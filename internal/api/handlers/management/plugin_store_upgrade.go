package management

import (
	"fmt"
	"net/http"
	"sync"

	"github.com/gin-gonic/gin"
	"github.com/router-for-me/CLIProxyAPI/v7/internal/config"
	"github.com/router-for-me/CLIProxyAPI/v7/internal/pluginstore"
)

type pluginUpgradeBlockedError struct{ err error }

func (e *pluginUpgradeBlockedError) Error() string { return e.err.Error() }
func (e *pluginUpgradeBlockedError) Unwrap() error { return e.err }

type pluginStoreInstallKey struct {
	handler *Handler
	id      string
}

type pluginStoreInstallLock struct {
	mu   sync.Mutex
	refs int
}

var pluginStoreInstallLocks = struct {
	sync.Mutex
	entries map[pluginStoreInstallKey]*pluginStoreInstallLock
}{entries: make(map[pluginStoreInstallKey]*pluginStoreInstallLock)}

// All store installs share this lock, including explicit rollbacks. Entries are
// removed after their last waiter; no handler or plugin ID is retained forever.
func lockPluginStoreInstall(handler *Handler, id string) func() {
	key := pluginStoreInstallKey{handler: handler, id: id}
	pluginStoreInstallLocks.Lock()
	entry := pluginStoreInstallLocks.entries[key]
	if entry == nil {
		entry = &pluginStoreInstallLock{}
		pluginStoreInstallLocks.entries[key] = entry
	}
	entry.refs++
	pluginStoreInstallLocks.Unlock()
	entry.mu.Lock()
	return func() {
		entry.mu.Unlock()
		pluginStoreInstallLocks.Lock()
		entry.refs--
		if entry.refs == 0 {
			delete(pluginStoreInstallLocks.entries, key)
		}
		pluginStoreInstallLocks.Unlock()
	}
}

func pluginStoreCandidateManifest(source pluginstore.Source, plugin pluginstore.Plugin, version string) (pluginstore.Manifest, error) {
	if pluginstore.PluginInstallType(plugin) == pluginstore.InstallTypeDirect {
		return pluginStoreDirectManifest(source, plugin, version)
	}
	return pluginstore.ManifestFromRelease(source, plugin, pluginstore.Release{TagName: version})
}

func pluginStoreUpgradeManifest(item config.PluginInstanceConfig, candidate pluginstore.Manifest, goos, goarch string) (pluginstore.Manifest, error) {
	storeNode := pluginStoreConfigNode(item)
	if storeNode == nil {
		return pluginstore.Manifest{}, fmt.Errorf("installed store provenance unavailable; use an explicit version install")
	}
	var installed pluginstore.Manifest
	if errDecode := storeNode.Decode(&installed); errDecode != nil {
		return pluginstore.Manifest{}, fmt.Errorf("installed store provenance is invalid")
	}
	return pluginstore.UpgradeManifest(installed, candidate, goos, goarch)
}

func writePluginStoreUpgradeBlocked(c *gin.Context, err error) {
	c.JSON(http.StatusConflict, gin.H{
		"error":   "plugin_store_upgrade_blocked",
		"message": err.Error(),
	})
}
