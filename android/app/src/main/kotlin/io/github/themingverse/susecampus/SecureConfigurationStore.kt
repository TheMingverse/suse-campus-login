package io.github.themingverse.susecampus

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import android.util.Base64
import io.github.themingverse.susecampus.core.*
import java.io.File
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.*

interface ConfigurationBlob {
    fun read(): ByteArray?
    fun write(bytes: ByteArray)
}

class AtomicConfigurationBlob(file: File) : ConfigurationBlob {
    private val atomic = AtomicFile(file)
    override fun read(): ByteArray? = if (atomic.baseFile.exists() || File(atomic.baseFile.path + ".bak").exists()) atomic.readFully() else null
    override fun write(bytes: ByteArray) {
        atomic.baseFile.parentFile?.mkdirs()
        val output = atomic.startWrite()
        try { output.write(bytes); atomic.finishWrite(output) }
        catch (error: Exception) { atomic.failWrite(output); throw error }
    }
}

class SecureConfigurationStore(
    context: Context,
    private val alias: String = "suse-campus-config-v1",
    private val blob: ConfigurationBlob = AtomicConfigurationBlob(File(context.noBackupFilesDir, "account.enc")),
) : ConfigurationStore {
    private val mutex = Mutex()
    private val aad = "suse-campus-config-v1".toByteArray()
    private fun existingKey(): SecretKey? = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }.getKey(alias, null) as? SecretKey
    private fun key(): SecretKey = existingKey() ?: KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
        init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256).setRandomizedEncryptionRequired(true).build())
    }.generateKey()

    private fun loadUnlocked(): Configuration {
        val bytes = blob.read() ?: return Configuration()
        check(bytes.size in 1..65536)
        val envelope = Json.parseToJsonElement(bytes.toString(Charsets.UTF_8)).jsonObject
        check(envelope["version"]?.jsonPrimitive?.int == 1)
        val iv = Base64.decode(envelope.getValue("iv").jsonPrimitive.content, Base64.NO_WRAP)
        check(iv.size == 12)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, existingKey() ?: error("Saved key unavailable"), GCMParameterSpec(128, iv))
        cipher.updateAAD(aad)
        val plaintext = cipher.doFinal(Base64.decode(envelope.getValue("data").jsonPrimitive.content, Base64.NO_WRAP))
        try {
            val value = Json.parseToJsonElement(plaintext.toString(Charsets.UTF_8)).jsonObject
            val username = value.getValue("username").jsonPrimitive.content
            val password = value.getValue("password").jsonPrimitive.content
            val service = value.getValue("service").jsonPrimitive.content
            check(username.length <= 1024 && password.length <= 4096 && (service.isEmpty() || Protocol.validServiceName(service)))
            return Configuration(username, password, service, value.getValue("autoLogin").jsonPrimitive.boolean,
                value["block"]?.let { if (it is JsonNull) null else Block.valueOf(it.jsonPrimitive.content) },
                value.getValue("revision").jsonPrimitive.long)
        } finally { plaintext.fill(0) }
    }

    private fun writeUnlocked(config: Configuration) {
        require(config.username.length <= 1024 && config.password.length <= 4096 &&
            (config.service.isEmpty() || Protocol.validServiceName(config.service)))
        val plaintext = buildJsonObject {
            put("username", config.username); put("password", config.password); put("service", config.service)
            put("autoLogin", config.autoLogin); put("revision", config.revision)
            put("block", config.block?.let { JsonPrimitive(it.name) } ?: JsonNull)
        }.toString().toByteArray()
        try {
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.ENCRYPT_MODE, key()); cipher.updateAAD(aad)
            val ciphertext = cipher.doFinal(plaintext)
            val envelope = buildJsonObject {
                put("version", 1); put("iv", Base64.encodeToString(cipher.iv, Base64.NO_WRAP))
                put("data", Base64.encodeToString(ciphertext, Base64.NO_WRAP))
            }
            blob.write(envelope.toString().toByteArray())
        } finally { plaintext.fill(0) }
    }

    override suspend fun load(): Configuration = withContext(Dispatchers.IO) { mutex.withLock { loadUnlocked() } }
    override suspend fun save(configuration: Configuration) = withContext(Dispatchers.IO) {
        mutex.withLock {
            // Saving explicitly also repairs corrupt/missing-key configuration, but never does so on load.
            val previous = runCatching { loadUnlocked().revision }.getOrDefault(0)
            writeUnlocked(Configuration(configuration.username.trim(), configuration.password, configuration.service,
                configuration.autoLogin, null, maxOf(System.currentTimeMillis(), previous + 1)))
        }
    }
    override suspend fun block(revision: Long, value: Block?) = withContext(Dispatchers.IO) {
        mutex.withLock {
            val config = loadUnlocked()
            if (config.revision != revision) throw PortalException(Failure.CHANGED)
            writeUnlocked(config.withBlock(value))
        }
    }
}
