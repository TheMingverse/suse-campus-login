package io.github.themingverse.susecampus

import org.junit.Assert.*
import org.junit.Test

class WidgetPinControllerTest {
    private class Memory : WidgetPinPersistence {
        var value = PinState()
        var fail = false
        override fun read() = value
        override fun write(state: PinState) { if (fail) throw java.io.IOException(); value = state }
    }
    private class Gateway : WidgetPinGateway {
        var supported = true; var accepted = true; var error = false
        val requests = mutableListOf<Pair<WidgetSize, String>>()
        val cancelled = mutableListOf<String>()
        var homes = 0
        var acknowledge: ((String) -> Unit)? = null
        override fun supported() = supported
        override fun request(size: WidgetSize, token: String): Boolean {
            if (error) throw IllegalStateException()
            requests.add(size to token); acknowledge?.invoke(token); return accepted
        }
        override fun cancel(token: String) { cancelled.add(token) }
        override fun home(): Boolean { homes++; return true }
    }
    @Test fun acceptedRequestWaitsForConfirmationAndMergesClicks() {
        val gateway = Gateway(); val controller = WidgetPinController(gateway, Memory())
        controller.request(WidgetSize.SMALL); controller.request(WidgetSize.SMALL); controller.request(WidgetSize.WIDE)
        assertEquals(1, gateway.requests.size)
        assertEquals(PinPhase.WAITING, controller.state.value.phase)
        assertFalse(controller.state.value.message.contains("已添加到桌面"))
        assertEquals(0, gateway.homes)
    }
    @Test fun onlyMatchingCallbackConfirms() {
        val gateway = Gateway(); val controller = WidgetPinController(gateway, Memory())
        controller.request(WidgetSize.WIDE)
        controller.confirmed("unknown")
        assertEquals(PinPhase.WAITING, controller.state.value.phase)
        controller.confirmed(gateway.requests.single().second)
        assertEquals(PinPhase.SUCCESS, controller.state.value.phase)
        assertNull(controller.state.value.token)
    }
    @Test fun cancellationWithoutCallbackNeverBecomesFailureOrRetriesAutomatically() {
        val gateway = Gateway(); val memory = Memory(); val controller = WidgetPinController(gateway, memory)
        controller.request(WidgetSize.SMALL)
        val recreated = WidgetPinController(gateway, memory)
        assertEquals(PinPhase.WAITING, recreated.state.value.phase)
        assertEquals(1, gateway.requests.size)
    }
    @Test fun unsupportedLauncherUsesManualInstructionsWithoutRequest() {
        val gateway = Gateway().apply { supported = false }
        val controller = WidgetPinController(gateway, Memory()); controller.request(WidgetSize.SMALL)
        assertEquals(PinPhase.MANUAL, controller.state.value.phase)
        assertTrue(gateway.requests.isEmpty()); assertEquals(0, gateway.homes)
    }
    @Test fun declinedRequestDoesNotClaimSuccess() {
        val gateway = Gateway().apply { accepted = false }
        val controller = WidgetPinController(gateway, Memory()); controller.request(WidgetSize.WIDE)
        assertEquals(PinPhase.MANUAL, controller.state.value.phase)
        assertEquals(1, gateway.cancelled.size)
    }
    @Test fun platformExceptionIsRecoverable() {
        val gateway = Gateway().apply { error = true }
        val controller = WidgetPinController(gateway, Memory()); controller.request(WidgetSize.SMALL)
        assertEquals(PinPhase.MANUAL, controller.state.value.phase)
        gateway.error = false; controller.retry()
        assertEquals(PinPhase.WAITING, controller.state.value.phase)
    }
    @Test fun explicitRetryReplacesTokenAndIgnoresLateCallback() {
        val gateway = Gateway(); val controller = WidgetPinController(gateway, Memory())
        controller.request(WidgetSize.WIDE); val old = gateway.requests.last().second
        controller.retry(); val current = gateway.requests.last().second
        assertNotEquals(old, current); assertTrue(old in gateway.cancelled)
        controller.confirmed(old); assertEquals(PinPhase.WAITING, controller.state.value.phase)
        controller.confirmed(current); assertEquals(PinPhase.SUCCESS, controller.state.value.phase)
    }
    @Test fun explicitRetryCanChooseAnotherSizeAfterCancelledDialog() {
        val gateway = Gateway(); val controller = WidgetPinController(gateway, Memory())
        controller.request(WidgetSize.SMALL)
        controller.retry(WidgetSize.WIDE)
        assertEquals(listOf(WidgetSize.SMALL, WidgetSize.WIDE), gateway.requests.map { it.first })
        assertEquals(WidgetSize.WIDE, controller.state.value.size)
    }
    @Test fun callbackAfterProcessRecreationConfirmsSavedRequest() {
        val memory = Memory(); val gateway = Gateway()
        WidgetPinController(gateway, memory).request(WidgetSize.SMALL)
        val recreated = WidgetPinController(gateway, memory)
        recreated.confirmed(gateway.requests.last().second)
        assertEquals(PinPhase.SUCCESS, recreated.state.value.phase)
    }
    @Test fun persistenceFailureDoesNotLaunchUntrackableRequest() {
        val gateway = Gateway(); val controller = WidgetPinController(gateway, Memory().apply { fail = true })
        controller.request(WidgetSize.SMALL)
        assertEquals(PinPhase.MANUAL, controller.state.value.phase)
        assertTrue(gateway.requests.isEmpty())
    }
    @Test fun synchronousSuccessIsNotOverwrittenByRequestReturn() {
        val gateway = Gateway(); val controller = WidgetPinController(gateway, Memory())
        gateway.acknowledge = controller::confirmed
        controller.request(WidgetSize.SMALL)
        assertEquals(PinPhase.SUCCESS, controller.state.value.phase)
    }
    @Test fun onlyExplicitHomeActionLeavesTheApp() {
        val gateway = Gateway(); val controller = WidgetPinController(gateway, Memory())
        controller.request(WidgetSize.SMALL)
        assertEquals(0, gateway.homes)
        assertTrue(controller.returnHome()); assertEquals(1, gateway.homes)
    }
}
