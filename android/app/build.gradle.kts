import java.util.Properties
import groovy.json.JsonSlurper

plugins {
    id("com.android.application")
    kotlin("android")
    id("org.jetbrains.kotlin.plugin.compose")
}
val campusVersion = Properties().apply {
    rootProject.file("version.properties").inputStream().use { load(it) }
}
val campusVersionName = requireNotNull(campusVersion.getProperty("versionName"))
val campusVersionCode = requireNotNull(campusVersion.getProperty("versionCode")).toInt()
require(Regex("(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)(?:-(?:alpha|beta|rc)\\.[1-9][0-9]*)?").matches(campusVersionName))
require(campusVersionCode in 4..2100000000)
val updateTrustDirectory = layout.buildDirectory.dir("generated/updateTrust/res")
val generateUpdateTrust by tasks.registering {
    inputs.file(rootProject.file("release-identity.json"))
    inputs.file(rootProject.file("update-sources.json"))
    outputs.dir(updateTrustDirectory)
    doLast {
        val identity = JsonSlurper().parse(rootProject.file("release-identity.json")) as Map<*, *>
        val appId = identity["applicationId"] as String
        val repository = identity["githubRepository"] as String
        val fingerprint = (identity["signingCertificateSha256"] as String).replace(":", "").lowercase()
        val sources = JsonSlurper().parse(rootProject.file("update-sources.json")) as Map<*, *>
        require(sources.keys == setOf("giteeRepository"))
        val gitee = sources["giteeRepository"] as String? ?: ""
        require(gitee.isEmpty() || Regex("[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+").matches(gitee) &&
            gitee.split('/').none { it in setOf(".", "..") })
        require(appId == "io.github.themingverse.susecampus")
        require(repository == "TheMingverse/suse-campus-login")
        require(Regex("[0-9a-f]{64}").matches(fingerprint))
        val output = updateTrustDirectory.get().file("values/update_trust.xml").asFile
        output.parentFile.mkdirs()
        output.writeText("""<resources>
            <string name="update_application_id" translatable="false">$appId</string>
            <string name="update_github_repository" translatable="false">$repository</string>
            <string name="update_certificate_sha256" translatable="false">$fingerprint</string>
            <string name="update_gitee_repository" translatable="false">$gitee</string>
        </resources>""".trimIndent())
    }
}
tasks.named("preBuild") { dependsOn(generateUpdateTrust) }
android {
    namespace = "io.github.themingverse.susecampus"
    compileSdk = 36
    buildToolsVersion = "35.0.0"
    defaultConfig {
        applicationId = "io.github.themingverse.susecampus"
        minSdk = 29
        targetSdk = 36
        versionCode = campusVersionCode
        versionName = campusVersionName
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }
    buildFeatures { compose = true }
    sourceSets.getByName("main").res.srcDir(updateTrustDirectory)
    buildTypes {
        getByName("release") {
            isDebuggable = false
            isMinifyEnabled = false
            isShrinkResources = false
            // Signing happens outside Gradle, using tools/android_release.py.
            signingConfig = null
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    packaging { resources.excludes += "/META-INF/{AL2.0,LGPL2.1}" }
    testOptions { unitTests.isReturnDefaultValues = true; unitTests.isIncludeAndroidResources = true }
}
dependencies {
    implementation(project(":core"))
    implementation(platform("androidx.compose:compose-bom:2025.10.00"))
    implementation("androidx.activity:activity-compose:1.11.0")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.9.4")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.9.4")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui-tooling-preview")
    debugImplementation("androidx.compose.ui:ui-tooling")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.9.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.robolectric:robolectric:4.16")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.10.2")
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
    androidTestImplementation(platform("androidx.compose:compose-bom:2025.10.00"))
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
    androidTestImplementation("androidx.test:runner:1.7.0")
}

// Android 16's Robolectric system image needs Java 21. Production bytecode remains Java 17.
tasks.withType<Test>().configureEach {
    systemProperty("suse.test.versionName", campusVersionName)
    systemProperty("suse.test.versionCode", campusVersionCode.toString())
    providers.environmentVariable("SUSE_TEST_JAVA_HOME").orNull?.let { testJava ->
        val javaBinary = if (System.getProperty("os.name").startsWith("Windows")) "java.exe" else "java"
        executable = "$testJava/bin/$javaBinary"
    }
}
