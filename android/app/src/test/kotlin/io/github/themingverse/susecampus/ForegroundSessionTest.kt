package io.github.themingverse.susecampus

import org.junit.Assert.*
import org.junit.Test

class ForegroundSessionTest {
    @Test fun onlyOncePerForegroundSession() {
        val session = ForegroundSession()
        assertFalse(session.consume())
        session.foreground(); assertTrue(session.consume()); assertFalse(session.consume())
        session.foreground(); assertFalse(session.consume()) // Rotation does not call background().
        session.background(); session.foreground(); assertTrue(session.consume())
    }
    @Test fun permissionOrSettingsReturnDoesNotRepeatAutomaticLogin() {
        val session = ForegroundSession()
        session.foreground(); assertTrue(session.consume())
        session.externalFlow(); session.background(); session.foreground()
        assertFalse(session.consume())
    }
}
