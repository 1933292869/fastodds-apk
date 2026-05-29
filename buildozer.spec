[app]
title = 极速赔率
package.name = fastodds
package.domain = org.fastodds
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,txt
version = 1.0
requirements = python3,kivy,aiohttp,pandas,lxml
orientation = portrait
osx.python_version = 3
osx.kivy_version = 2.2.0
fullscreen = 0

# Android
android.permissions = INTERNET,ACCESS_NETWORK_STATE,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE
android.api = 33
android.minapi = 24
android.ndk = 25b
android.sdk = 33
android.accept_sdk_license = True
android.archs = arm64-v8a,armeabi-v7a
android.entitlements =
android.add_src =

# iOS
ios.codesign.allowed = false

[buildozer]
log_level = 2
warn_on_root = 1
