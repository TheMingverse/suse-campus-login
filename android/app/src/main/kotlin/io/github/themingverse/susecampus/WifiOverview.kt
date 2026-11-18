package io.github.themingverse.susecampus

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.location.LocationManager
import android.net.*
import android.net.wifi.WifiInfo
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import io.github.themingverse.susecampus.core.Protocol

/** Foreground-only UI observation; it sends no requests and cannot start authentication. */
class WifiOverview(private val context: Context, private val update: (String, Boolean) -> Unit) : AutoCloseable {
    private val manager = context.getSystemService(ConnectivityManager::class.java)
    private val wifi = context.getSystemService(WifiManager::class.java)
    private val capabilities = mutableMapOf<Network, NetworkCapabilities>()
    private val links = mutableMapOf<Network, LinkProperties>()
    private var previous: String? = null
    private var registered = false
    private fun publish() {
        val allowed = context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED &&
            context.getSystemService(LocationManager::class.java).isLocationEnabled
        val identity = capabilities.entries.sortedBy { it.key.networkHandle }.joinToString("|") { (network, caps) ->
            val name = if (allowed) {
                if (Build.VERSION.SDK_INT >= 31) (caps.transportInfo as? WifiInfo)?.ssid
                else { @Suppress("DEPRECATION") wifi.connectionInfo?.ssid }
            } else null
            listOf(network.networkHandle.toString(), name.orEmpty(), links[network]?.linkAddresses.toString(),
                links[network]?.routes.toString(), links[network]?.dnsServers.toString()).joinToString(";")
        }
        val name = if (allowed && capabilities.size == 1) {
            val info = if (Build.VERSION.SDK_INT >= 31) capabilities.values.single().transportInfo as? WifiInfo
                else { @Suppress("DEPRECATION") wifi.connectionInfo }
            info?.ssid?.removeSurrounding("\"")?.takeUnless { it == "<unknown ssid>" }
        } else null
        val text = when {
            capabilities.isEmpty() -> "未连接 Wi-Fi"
            capabilities.size > 1 -> "检测到多个 Wi-Fi，暂不认证"
            name == null -> "Wi-Fi 已连接，名称暂不可读取"
            name in Protocol.ssids -> "已连接校园 Wi-Fi · $name"
            else -> "已连接其他 Wi-Fi，不提交认证"
        }
        val changed = previous != null && identity != previous
        previous = identity
        update(text, changed)
    }
    private val events = object : ConnectivityManager.NetworkCallback() {
        override fun onCapabilitiesChanged(network: Network, caps: NetworkCapabilities) { capabilities[network] = caps; publish() }
        override fun onLinkPropertiesChanged(network: Network, properties: LinkProperties) { links[network] = properties; publish() }
        override fun onLost(network: Network) { capabilities.remove(network); links.remove(network); publish() }
    }
    private val callback = if (Build.VERSION.SDK_INT >= 31) object : ConnectivityManager.NetworkCallback(ConnectivityManager.NetworkCallback.FLAG_INCLUDE_LOCATION_INFO) {
        override fun onCapabilitiesChanged(network: Network, caps: NetworkCapabilities) = events.onCapabilitiesChanged(network, caps)
        override fun onLinkPropertiesChanged(network: Network, properties: LinkProperties) = events.onLinkPropertiesChanged(network, properties)
        override fun onLost(network: Network) = events.onLost(network)
    } else events
    fun start() {
        manager.registerNetworkCallback(NetworkRequest.Builder().addTransportType(NetworkCapabilities.TRANSPORT_WIFI).build(), callback,
            Handler(Looper.getMainLooper()))
        registered = true
        publish()
    }
    override fun close() {
        if (registered) { runCatching { manager.unregisterNetworkCallback(callback) }; registered = false }
        capabilities.clear(); links.clear()
    }
}
