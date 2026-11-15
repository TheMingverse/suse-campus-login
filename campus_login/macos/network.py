"""Read current physical interfaces using public macOS frameworks."""
import socket

from ..models import NetworkConnection, NetworkSnapshot


def snapshot_from_records(records):
    """Normalize framework results; unreadable wireless never becomes Ethernet."""
    connections, unavailable = [], False
    for record in records:
        if record['kind'] not in ('wifi', 'ethernet') or not record.get('active'):
            continue
        unavailable |= record['kind'] == 'wifi' and not record.get('ssid')
        connections.append(NetworkConnection(
            record['interface'], record['index'], record['kind'], record['name'],
            record.get('address', ''), record.get('router', ''),
            record.get('ssid') or '', record.get('bssid') or ''))
    return NetworkSnapshot(tuple(sorted(connections, key=lambda c: c.interface_index)), unavailable)


def network_snapshot():
    import SystemConfiguration as SC
    import CoreWLAN
    store = SC.SCDynamicStoreCreate(None, 'SUSECampusLogin', None, None)
    if store is None:
        raise OSError('无法读取网络状态')
    wifi = CoreWLAN.CWWiFiClient.sharedWiFiClient()
    records = []
    for interface in SC.SCNetworkInterfaceCopyAll() or []:
        kind = SC.SCNetworkInterfaceGetInterfaceType(interface)
        if kind not in (SC.kSCNetworkInterfaceTypeIEEE80211, SC.kSCNetworkInterfaceTypeEthernet):
            continue
        name = SC.SCNetworkInterfaceGetBSDName(interface)
        if not name:
            continue
        # Physical Ethernet/Wi-Fi devices use IOKit device paths. Exclude bridges/VPNs.
        path = SC.SCNetworkInterfaceGetHardwareAddressString(interface)
        if not path:
            continue
        state = SC.SCDynamicStoreCopyValue(store, f'State:/Network/Interface/{name}/IPv4') or {}
        link = SC.SCDynamicStoreCopyValue(store, f'State:/Network/Interface/{name}/Link') or {}
        address = next(iter(state.get('Addresses', [])), '')
        router = state.get('Router', '')
        # Per-service IPv4 state carries the router on many macOS versions.
        for key in SC.SCDynamicStoreCopyKeyList(store, 'State:/Network/Service/.*/IPv4') or []:
            service = SC.SCDynamicStoreCopyValue(store, key) or {}
            if service.get('InterfaceName') == name:
                router = service.get('Router', router)
        wireless = kind == SC.kSCNetworkInterfaceTypeIEEE80211
        ssid = bssid = ''
        if wireless:
            try:
                item = wifi.interfaceWithName_(name)
                if item:
                    ssid, bssid = item.ssid() or '', item.bssid() or ''
            except Exception:
                pass  # Missing wireless authorization must fail closed.
        try:
            index = socket.if_nametoindex(name)
        except OSError:
            continue
        records.append(dict(interface=name, index=index,
                            name=SC.SCNetworkInterfaceGetLocalizedDisplayName(interface) or name,
                            kind='wifi' if wireless else 'ethernet',
                            active=bool(link.get('Active', bool(address))), address=address,
                            router=router, ssid=ssid, bssid=bssid))
    return snapshot_from_records(records)
