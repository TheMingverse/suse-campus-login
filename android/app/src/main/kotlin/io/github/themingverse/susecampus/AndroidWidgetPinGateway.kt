package io.github.themingverse.susecampus

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.content.*
import android.net.Uri
import android.os.Bundle
import java.io.File
import kotlinx.serialization.json.*

class PinFile(context: Context) : WidgetPinPersistence {
    private val blob = AtomicConfigurationBlob(File(context.noBackupFilesDir, "widget-pin.json"))
    override fun read(): PinState {
        val bytes = blob.read() ?: return PinState()
        require(bytes.size < 4096)
        val value = Json.parseToJsonElement(bytes.toString(Charsets.UTF_8)).jsonObject
        return PinState(PinPhase.valueOf(value.getValue("phase").jsonPrimitive.content),
            WidgetSize.valueOf(value.getValue("size").jsonPrimitive.content),
            value["token"]?.let { if (it is JsonNull) null else it.jsonPrimitive.content })
    }
    override fun write(state: PinState) = blob.write(buildJsonObject {
        put("phase", state.phase.name); put("size", state.size.name)
        put("token", state.token?.let(::JsonPrimitive) ?: JsonNull)
    }.toString().toByteArray())
}

class AndroidWidgetPinGateway(private val context: Context) : WidgetPinGateway {
    companion object {
        const val ACTION = "io.github.themingverse.susecampus.WIDGET_PIN_CONFIRMED"
        fun callbackIntent(context: Context, token: String) = Intent(context, WidgetPinResultReceiver::class.java)
            .setAction(ACTION).setData(Uri.Builder().scheme("suse-widget-pin").authority("result").appendPath(token).build())
        fun callback(context: Context, token: String): PendingIntent = PendingIntent.getBroadcast(context, 0,
            callbackIntent(context, token), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    }
    override fun supported() = AppWidgetManager.getInstance(context).isRequestPinAppWidgetSupported
    override fun request(size: WidgetSize, token: String): Boolean {
        (context.applicationContext as CampusApplication).externalFlow()
        val provider = if (size == WidgetSize.SMALL) SmallLoginWidget::class.java else WideLoginWidget::class.java
        val extras = Bundle().apply {
            putParcelable(AppWidgetManager.EXTRA_APPWIDGET_PREVIEW, QuickWidgets.views(context, size == WidgetSize.WIDE, QuickResult(), allowLogin = false))
        }
        return AppWidgetManager.getInstance(context).requestPinAppWidget(ComponentName(context, provider), extras, callback(context, token))
    }
    override fun cancel(token: String) {
        PendingIntent.getBroadcast(context, 0, callbackIntent(context, token), PendingIntent.FLAG_NO_CREATE or PendingIntent.FLAG_IMMUTABLE)?.cancel()
    }
    override fun home(): Boolean {
        context.startActivity(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        return true
    }
}

class WidgetPinResultReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != AndroidWidgetPinGateway.ACTION || intent.data?.scheme != "suse-widget-pin" || intent.data?.authority != "result") return
        val token = intent.data?.lastPathSegment ?: return
        // Immutable callback retains our request identity; launcher-filled widget IDs are not needed.
        (context.applicationContext as CampusApplication).widgetPins.confirmed(token)
    }
}
