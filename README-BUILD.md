# Pixie Dust — دليل البناء

هذا المشروع تطبيق Android مكتوب بـ **Java** (بلا Kotlin، بلا Compose) مع محرك
Pixie Dust الأصلي بلغة **Python** عبر **Chaquopy**. الواجهة كلها views عادية،
وخدمة واحدة في الخلفية، والتصميم فاتح فقط.

- Package / applicationId: `ma.pixiedust.app`
- Version: `1.0.8` (versionCode `9`)
- minSdk `24` / targetSdk `36` / compileSdk `36`
- ABIs: `arm64-v8a` + `armeabi-v7a` فقط (بلا x86 وبلا محاكي)
- اللغات: English / Français
- إذن `INTERNET` مخصص فقط لفحص التحديث الاختياري وتنزيل الـ APK؛ بيانات الالتقاط لا تُرسل أبدًا

---

## 1. متطلبات البناء

| المكوّن | النسخة المستخدمة |
|---|---|
| JDK | `C:\Java\jdk-21.0.13+9` (JDK 17+ يكفي) |
| Android SDK | `C:\Android\Sdk` (platform 36 + build-tools 36.0.0) |
| Python | `C:\Python311\python.exe` (**Python 3.11 إلزامي** — Chaquopy 17.2 يدعم 3.11 لـ `armeabi-v7a`) |
| Gradle | wrapper مضمّن في المشروع (9.3.1) |

يجب أن يحتوي `local.properties` على:

```properties
sdk.dir=C:/Android/Sdk
```

إن كان Python 3.11 في مسار آخر، عدّل السطر في `app/build.gradle.kts`:

```kotlin
listOf("C:/Python311/python.exe", ...).firstOrNull { File(it).exists() }?.let { buildPython(it) }
```

إذا لم يجده البناء فسيفشل بـ `Couldn't find Python 3.11`.

---

## 2. البناء (Windows)

```powershell
$env:JAVA_HOME="C:\Java\jdk-21.0.13+9"
$env:PATH="C:\Python311;C:\Python311\Scripts;$env:PATH"
Set-Location "C:\Users\hp\Documents\PixieDust"

# release موقَّع
.\gradlew.bat :app:assembleRelease

# debug (اختياري)
.\gradlew.bat :app:assembleDebug
```

يخرج الـ APK في:

```
app\build\outputs\apk\release\app-release.apk
```

البناء الأول ينزّل الاعتماديات و Python 3.11 وقد يستغرق نحو 10 دقائق.
بعد ذلك يصبح كل بناء أسرع (1–3 دقائق).

---

## 3. التوقيع (release)

يقرأ المشروع `keystore.properties` من جذر المشروع (وهو غير مضمّن في git):

```properties
storeFile=pixie-release.jks
storePassword=...
keyAlias=pixiedust
keyPassword=...
```

أو من متغيرات البيئة: `KEYSTORE_PATH`, `STORE_PASSWORD`, `KEY_ALIAS`, `KEY_PASSWORD`.

المفتاح المسلَّم مع المشروع:

- keystore: `pixie-release.jks` (RSA 4096، صلاحية 10000 يوم)
- alias: `pixiedust`
- كلمة السر: موجودة في `keystore.properties` وفي `KEYSTORE-INFO.txt` المسلَّم مع الـ APK.

> **مهم:** احفظ `pixie-release.jks` وكلمة السر. بلا هذا المفتاح لا يمكن تحديث
> التطبيق في Play Store ولا تثبيت نسخة جديدة فوق القديمة.

---

## 4. التحقق من الـ APK

```powershell
$bt="C:\Android\Sdk\build-tools\36.0.0"
& "$bt\apksigner.bat" verify --print-certs --verbose app\build\outputs\apk\release\app-release.apk
& "$bt\aapt2.exe" dump badging app\build\outputs\apk\release\app-release.apk
```

المتوقع:

- `Verifies` و`Verified using v2 scheme (APK Signature Scheme v2): true`
- package `ma.pixiedust.app`، versionCode `9`، versionName `1.0.8`
- `native-code: 'arm64-v8a' 'armeabi-v7a'`
- locales تتضمن `en`, `fr`

---

## 5. بنية الكود

```
app/src/main/java/ma/pixiedust/app/
  PixieApp.java              Application: تشغيل Python + singletons
  core/Data.java             حاويات البيانات (AccessPoint, Verify, Crack, Handshake…)
  core/Prefs.java            SharedPreferences (بلا DataStore) + ترحيل الإعدادات
  core/Bridge.java           غلاف Java على pixie_android.bridge
  core/Repo.java             خيط واحد للمحرك + حالة قابلة للمراقبة
  core/PixieError.java       تحويل الأخطاء (بلا «PIN خاطئ» في حالة no_m1)
  usb/UsbOtg.java            إذن OTG + file descriptor
  usb/Adapters.java          قائمة الشرائح المدعومة
  service/AttackService.java خدمة أمامية + wake lock
  ui/*.java                  Scan, Details, Attack, Result, Settings, Drivers,
                             Disclaimer, About + ApAdapter + views
app/src/main/python/         المحرك: pixie, wifit3, pixie_android
  pixie/live.py              البحث، التقاط M1–M3، التقاط المصافحة السلبي، عدّ العملاء
  pixie_android/bridge.py    عقد JSON آمن نحو Java
  pixie_android/libusb_fd.py libusb عبر fd (إصلاح configuration على Android)
```

الواجهة تقرأ الحالة من `Repo` (listener + handler على main thread)، والمحرك يعمل
في خيط واحد `pixie-engine` — لذلك لا تحدث عمليتان على USB في الوقت نفسه.

---

## 6. قواعد السلامة المطبَّقة في الكود

- **Pixie Dust فقط**: بلا OneShot، بلا تخمين PIN عبر الإنترنت، بلا PBC/WEP،
  بلا deauth flood، بلا root، بلا `wpa_supplicant`.
- **محاولة WPS PIN واحدة** في كل تشغيل: `auto_attack(..., auto_verify)` ينفّذ
  التقاط + بحثًا دون اتصال + معاملة واحدة. لا إعادة محاولة تلقائية بعد NACK أو قفل.
- موافقة واحدة في البداية (Disclaimer) + تأكيد قبل كل محاولة في شاشة التفاصيل
  + تأكيد منفصل قبل التقاط المصافحة.
- لا تُكتب بيانات الاعتماد في سجلات التطبيق؛ تُحفظ بيانات PIN/كلمة المرور المستعادة
  محليًا في سجل خاص بالتطبيق على الجهاز. لا توجد صلاحية إنترنت ولا إرسال لهذه البيانات.
- `no_m1` يُعرض كـ «الموجّه لم يبدأ جلسة WPS جديدة»، وليس «PIN خاطئ».
- لا كلمة سر مخترعة: إن لم يُرجع الموجّه PSK، تقول الشاشة ذلك بوضوح.
- التحقق من handshake سلبي، مع خيار deauth محدود وموجّه للعملاء المرصودين فقط؛ لا توجد عاصفة deauth.
- لا يُكتب ملف pcap ولا يُسجل كنجاح إلا بعد تحقق زوج handshake قابل للكسر عبر wifit3.

---

## 7. حدود ومحاذير

- **لم يُختبر على هاتف حقيقي مع محوّل USB OTG في هذه البيئة.** البناء وحده لا يثبت
  أن الـ RF يعمل على عتاد معيّن. إصلاح `get_configuration` لـ MT7601U موجود في
  `libusb_fd.py` لكنه لم يُتحقق منه على جهاز فعلي بعد.
- نجاح Pixie Dust يعتمد على شريحة الموجّه و PRNG الخاص به. كثير من الموجّهات
  الحديثة تستخدم حماية تُفشل المحاولة.
- قفل WPS حقيقي: المحاولة الواحدة قد تستهلك فرصة أو تحتاج إعادة تشغيل للموجّه.
- التقاط handshake لا ينجح إلا إذا التقط التطبيق زوجًا صالحًا قابلًا للكسر؛ عند عدمه
  لا يُنشأ ملف pcap. الملفات المحفوظة بصيغة linktype 105 (لقراءتها بـ
  `hcxpcapngtool` ثم `hashcat -m 22000`).
- سجل النتائج محلي وخاص بالتطبيق، ويشمل المصافحات المتحقق منها والـ PIN/كلمات المرور
  المستعادة. لا يُرسل السجل أبدًا؛ الشبكة تُستعمل فقط لفحص التحديث الاختياري، ويمكن مسح السجل من شاشة History.
- عدّاد العملاء تقديري: يعتمد على عناوين MAC أحادية الإرسال في إطارات البيانات
  المرصودة، لا على استعلام للموجّه.
- حجم الـ APK نحو 30 MB لأنه يضم Python 3.11 والمحرك والـ firmware.

---

## 8. الترخيص

GPL-2.0. النص الكامل في `LICENSE` و`NOTICE` مع الأرشيف.
