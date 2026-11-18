package io.github.themingverse.susecampus

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import io.github.themingverse.susecampus.core.*
import java.io.File
import java.security.KeyStore
import java.util.UUID
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class SecureConfigurationStoreTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val alias = "suse-test-${UUID.randomUUID()}"
    private val file = File(context.cacheDir, "$alias.enc")
    private val configuration = Configuration("synthetic-user", "synthetic-secret+&汉字🙂", "测试服务", true)
    @After fun clean() {
        KeyStore.getInstance("AndroidKeyStore").apply { load(null); deleteEntry(alias) }
        file.delete(); File(file.path + ".bak").delete()
    }
    private fun store(blob: ConfigurationBlob = AtomicConfigurationBlob(file)) = SecureConfigurationStore(context, alias, blob)

    @Test fun realKeystoreRoundTripRandomIvAndPersistentBlock() = runBlocking {
        val store = store()
        store.save(configuration)
        val first = file.readBytes()
        assertFalse(first.toString(Charsets.UTF_8).contains("synthetic-secret"))
        assertFalse(first.toString(Charsets.UTF_8).contains("synthetic-user"))
        assertEquals(configuration.password, store().load().password)
        store.save(configuration)
        assertFalse(first.contentEquals(file.readBytes()))
        val revision = store.load().revision
        store.block(revision, Block.CREDENTIALS)
        assertEquals(Block.CREDENTIALS, store().load().block)
        store.save(configuration)
        assertNull(store.load().block)
    }

    @Test fun tamperingIsRejectedWithoutErasingCiphertext() = runBlocking {
        store().save(configuration)
        val bytes = file.readBytes()
        bytes[bytes.lastIndex - 10] = (bytes[bytes.lastIndex - 10].toInt() xor 1).toByte()
        file.writeBytes(bytes)
        try { store().load(); fail("Corruption must require reconfiguration") } catch (_: Exception) { }
        assertArrayEquals(bytes, file.readBytes())
    }

    @Test fun missingKeyIsRejectedAndExplicitSaveCanRepair() = runBlocking {
        store().save(configuration)
        KeyStore.getInstance("AndroidKeyStore").apply { load(null); deleteEntry(alias) }
        try { store().load(); fail("Missing key must not load an empty password") } catch (_: Exception) { }
        store().save(configuration)
        assertEquals(configuration.password, store().load().password)
    }

    @Test fun failedSavePreservesPreviousEncryptedConfiguration() = runBlocking {
        val atomic = AtomicConfigurationBlob(file)
        var failWrite = false
        val store = store(object : ConfigurationBlob {
            override fun read() = atomic.read()
            override fun write(bytes: ByteArray) { if (failWrite) throw java.io.IOException("synthetic failure"); atomic.write(bytes) }
        })
        store.save(configuration)
        failWrite = true
        try { store.save(Configuration("other-user", "other-secret", "测试服务")); fail() } catch (_: Exception) { }
        assertEquals(configuration.password, store.load().password)
    }
}
