import java.io.File
import java.util.Properties

plugins {
    id("com.android.application")
    id("com.chaquo.python")
}

// ---------------------------------------------------------------------------
// Signing: read keystore.properties (git-ignored) or the CI environment.
// ---------------------------------------------------------------------------
val keystorePropsFile = rootProject.file("keystore.properties")
val keystoreProps = Properties().apply {
    if (keystorePropsFile.exists()) {
        keystorePropsFile.inputStream().use { load(it) }
    }
}

fun signingValue(key: String, env: String): String? =
    keystoreProps.getProperty(key) ?: System.getenv(env)

val signStoreFile = (signingValue("storeFile", "KEYSTORE_PATH") ?: "pixie-release.jks")
    .let { if (File(it).isAbsolute) File(it) else rootProject.file(it) }
val signStorePassword = signingValue("storePassword", "STORE_PASSWORD")
val signKeyAlias = signingValue("keyAlias", "KEY_ALIAS") ?: "pixiedust"
val signKeyPassword = signingValue("keyPassword", "KEY_PASSWORD") ?: signStorePassword

android {
    namespace = "ma.pixiedust.app"
    compileSdk = 36

    defaultConfig {
        applicationId = "ma.pixiedust.app"
        minSdk = 24
        targetSdk = 36
        versionCode = 8
        versionName = "1.0.7"

        // ARM phones only: 64-bit and 32-bit. No emulator ABIs, which keeps the APK smaller.
        ndk {
            abiFilters += listOf("arm64-v8a", "armeabi-v7a")
        }
    }

    signingConfigs {
        create("release") {
            if (signStoreFile.exists()) {
                storeFile = signStoreFile
                storePassword = signStorePassword
                this.keyAlias = signKeyAlias
                this.keyPassword = signKeyPassword
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            signingConfig = signingConfigs.getByName("release")
        }
        debug {
            applicationIdSuffix = ".debug"
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        viewBinding = true
    }

    dependenciesInfo {
        // Do not embed the dependency metadata blob in the APK.
        includeInApk = false
        includeInBundle = true
    }

    packaging {
        // Extract native libraries to ApplicationInfo.nativeLibraryDir. libusb is loaded with
        // ctypes.CDLL(<dir>/libusb-1.0.so), which needs a real file on disk.
        jniLibs {
            useLegacyPackaging = true
        }
        resources {
            excludes += listOf(
                "META-INF/*.kotlin_module",
                "META-INF/DEPENDENCIES",
                "META-INF/LICENSE*",
                "META-INF/NOTICE*"
            )
        }
    }
}

// The changelog in docs/update.json is mirrored into the APK as a notes-only
// resource, so "What's new" works on the first launch after an update even
// offline. Download URL/SHA are deliberately left out of the bundled copy.
val syncUpdateChangelog by tasks.registering {
    val source = rootProject.file("docs/update.json")
    val target = project.file("src/main/res/raw/update_changelog.json")
    inputs.file(source)
    outputs.file(target)
    doLast {
        @Suppress("UNCHECKED_CAST")
        val root = groovy.json.JsonSlurper()
            .parse(source) as Map<String, Any?>
        val notes = linkedMapOf<String, Any?>(
            "versionCode" to root["versionCode"],
            "versionName" to root["versionName"],
            "changelog" to root["changelog"]
        )
        target.parentFile.mkdirs()
        target.writeText(groovy.json.JsonOutput.toJson(notes), Charsets.UTF_8)
    }
}

tasks.named("preBuild").configure { dependsOn(syncUpdateChangelog) }
tasks.matching {
    it.name.startsWith("merge") && it.name.contains("Resources")
}.configureEach { dependsOn(syncUpdateChangelog) }

dependencies {
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.constraintlayout:constraintlayout:2.1.4")
    implementation("androidx.recyclerview:recyclerview:1.3.2")
    implementation("androidx.core:core:1.13.1")

    testImplementation("junit:junit:4.13.2")
}

chaquopy {
    defaultConfig {
        version = "3.11"
        // The USB driver stack is imported as real files, not from the APK zip.
        extractPackages("wifit3")

        // Local Windows builds often have Python outside PATH; use it when present.
        listOf(
            "C:/Python311/python.exe",
            "C:/Python311/python.exe".replace('/', '\\')
        ).firstOrNull { File(it).exists() }?.let { buildPython(it) }

        pip {
            install("pyusb")
            install("platformdirs")
        }
    }
}
