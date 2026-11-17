# Keep the Python/Android bridge entry points reachable.
-keep class com.chaquo.python.** { *; }
-keep class ma.pixiedust.app.core.Bridge { *; }

# Chaquopy reflects on Java objects handed to Python (log callbacks).
-keepclassmembers class ma.pixiedust.app.core.LogSink { public *; }

# AndroidX/Material reflect on these.
-keep class androidx.appcompat.widget.** { *; }
-dontwarn org.conscrypt.**
