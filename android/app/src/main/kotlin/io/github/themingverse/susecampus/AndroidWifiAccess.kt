package io.github.themingverse.susecampus

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.location.LocationManager
import android.net.*
import android.net.wifi.WifiInfo
import android.net.wifi.WifiManager
import android.os.Build
import io.github.themingverse.susecampus.core.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import okhttp3.Dns
import okhttp3.OkHttpClient
import java.util.concurrent.atomic.AtomicBoolean

class AndroidWifiAccess(private val context: Context) : WifiAccess {
    private val manager = context.getSystemService(ConnectivityManager::class.java)
    private val wifiManager = context.getSystemService(WifiManager::class.java)

    private fun checkPermissions() {
        if (context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED ||
            !context.getSystemService(LocationManager::class.java).isLocationEnabled) throw PortalException(Failure.PERMISSION)
    }

    override suspend fun acquire(): WifiLease {
        checkPermissions()
        val lease = Lease()
        try { lease.register(); lease.select(); return lease }
        catch (error: Exception) { lease.close(); throw error }
    }

    private inner class Lease : WifiLease {
        private val lock = Any()
        private val closed = AtomicBoolean(false)
        private var registered = false
        private val capabilities = mutableMapOf<Network, NetworkCapabilities>()
        private val links = mutableMapOf<Network, LinkProperties>()
        private var selected: Network? = null
        private var identity: String? = null
        private var http: HttpTransport? = null
        override val transport get() = http ?: error("Network unavailable")
        override val invalidated = MutableStateFlow(false)

        private fun ssid(caps: NetworkCapabilities): String? {
            val info = if (Build.VERSION.SDK_INT >= 31) caps.transportInfo as? WifiInfo else {
                @Suppress("DEPRECATION")
                wifiManager.connectionInfo
            }
            return info?.ssid?.removeSurrounding("\"")?.takeUnless { it == "<unknown ssid>" }
        }
        private fun signature(network: Network): String? {
            val caps = capabilities[network] ?: return null
            val link = links[network] ?: return null
            val name = ssid(caps) ?: return null
            val addresses = link.linkAddresses.map { it.toString() }.sorted()
            if (addresses.isEmpty()) return null
            // Never use device MAC as a protocol parameter; the portal provides its own opaque mac value.
            return listOf(network.networkHandle.toString(), name, link.interfaceName.orEmpty(),
                addresses.joinToString(), link.routes.map { it.toString() }.sorted().joinToString(),
                link.dnsServers.map { it.hostAddress.orEmpty() }.sorted().joinToString()).joinToString("|")
        }
        private fun changed() {
            selected?.let { network ->
                if (signature(network) != identity || capabilities.keys.any { it != network }) invalidated.value = true
            }
        }
        private val events = object : ConnectivityManager.NetworkCallback() {
            override fun onCapabilitiesChanged(network: Network, caps: NetworkCapabilities) = synchronized(lock) {
                capabilities[network] = caps; changed()
            }
            override fun onLinkPropertiesChanged(network: Network, properties: LinkProperties) = synchronized(lock) {
                links[network] = properties; changed()
            }
            override fun onLost(network: Network) = synchronized(lock) {
                capabilities.remove(network); links.remove(network)
                if (selected == network) invalidated.value = true
            }
            override fun onBlockedStatusChanged(network: Network, blocked: Boolean) = synchronized(lock) {
                if (blocked && selected == network) invalidated.value = true
            }
        }
        private val callback = if (Build.VERSION.SDK_INT >= 31) object : ConnectivityManager.NetworkCallback(ConnectivityManager.NetworkCallback.FLAG_INCLUDE_LOCATION_INFO) {
            override fun onCapabilitiesChanged(network: Network, caps: NetworkCapabilities) = events.onCapabilitiesChanged(network, caps)
            override fun onLinkPropertiesChanged(network: Network, properties: LinkProperties) = events.onLinkPropertiesChanged(network, properties)
            override fun onLost(network: Network) = events.onLost(network)
            override fun onBlockedStatusChanged(network: Network, blocked: Boolean) = events.onBlockedStatusChanged(network, blocked)
        } else events
        fun register() {
            manager.registerNetworkCallback(NetworkRequest.Builder().addTransportType(NetworkCapabilities.TRANSPORT_WIFI).build(), callback)
            registered = true
        }
        suspend fun select() {
            // Wait only for the initial, asynchronous capability/link callbacks; never request or switch Wi-Fi.
            repeat(20) {
                val ready = synchronized(lock) { capabilities.isNotEmpty() && capabilities.keys.all { links.containsKey(it) } }
                if (ready) return@repeat
                delay(100)
            }
            checkPermissions()
            synchronized(lock) {
                if (capabilities.isEmpty()) throw PortalException(Failure.NO_WIFI)
                if (capabilities.size != 1) throw PortalException(Failure.AMBIGUOUS)
                val (network, caps) = capabilities.entries.single()
                val name = ssid(caps) ?: throw PortalException(Failure.PERMISSION)
                if (name !in Protocol.ssids) throw PortalException(Failure.OUTSIDE)
                identity = signature(network) ?: throw PortalException(Failure.TEMPORARY)
                selected = network
                http = BoundHttpTransport(OkHttpClient.Builder().socketFactory(network.socketFactory)
                    .dns(object : Dns {
                        override fun lookup(hostname: String) = network.getAllByName(hostname).toList()
                    }).build())
            }
        }
        override fun guard() {
            checkPermissions()
            synchronized(lock) {
                if (closed.get() || invalidated.value || selected == null || signature(selected!!) != identity)
                    throw PortalException(Failure.CHANGED)
            }
        }
        override fun close() {
            if (!closed.compareAndSet(false, true)) return
            if (registered) runCatching { manager.unregisterNetworkCallback(callback) }
            http?.close()
            synchronized(lock) { capabilities.clear(); links.clear(); selected = null; identity = null }
        }
    }
}
