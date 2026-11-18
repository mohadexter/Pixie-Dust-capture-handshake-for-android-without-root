package ma.pixiedust.app.core;

import android.content.Context;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.content.pm.SigningInfo;
import android.os.Build;

import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.security.MessageDigest;

/**
 * Refuses to install anything that is not exactly the APK we published: the
 * SHA-256 from {@code update.json} must match, and the signing certificate must
 * be the one already installed on the phone. Without that second check a
 * compromised download URL could serve a different app.
 */
public final class ApkVerifier {

    public enum Result { OK, MISSING, HASH, SIGNATURE, ERROR }

    private ApkVerifier() {
    }

    public static Result verify(Context context, File apk, String expectedSha256) {
        if (apk == null || !apk.isFile() || apk.length() == 0L) {
            return Result.MISSING;
        }
        try {
            if (expectedSha256 != null && !expectedSha256.isEmpty()) {
                if (!sha256(apk).equalsIgnoreCase(expectedSha256)) {
                    return Result.HASH;
                }
            }
            return sameSignature(context, apk) ? Result.OK : Result.SIGNATURE;
        } catch (Exception ignored) {
            return Result.ERROR;
        }
    }

    public static String sha256(File file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream in = new FileInputStream(file)) {
            byte[] buffer = new byte[8192];
            int read;
            while ((read = in.read(buffer)) > 0) {
                digest.update(buffer, 0, read);
            }
        }
        StringBuilder out = new StringBuilder(64);
        for (byte b : digest.digest()) {
            out.append(String.format("%02x", b));
        }
        return out.toString();
    }

    @SuppressWarnings("deprecation")
    private static boolean sameSignature(Context context, File apk) throws Exception {
        PackageManager pm = context.getPackageManager();
        int flags = Build.VERSION.SDK_INT >= 28
                ? PackageManager.GET_SIGNING_CERTIFICATES
                : PackageManager.GET_SIGNATURES;
        PackageInfo installed = pm.getPackageInfo(context.getPackageName(), flags);
        PackageInfo candidate = pm.getPackageArchiveInfo(apk.getAbsolutePath(), flags);
        byte[] mine = firstSignature(installed);
        byte[] theirs = firstSignature(candidate);
        return mine != null && theirs != null && MessageDigest.isEqual(mine, theirs);
    }

    @SuppressWarnings("deprecation")
    private static byte[] firstSignature(PackageInfo info) {
        if (info == null) {
            return null;
        }
        Signature[] signatures = null;
        if (Build.VERSION.SDK_INT >= 28) {
            SigningInfo signing = info.signingInfo;
            if (signing != null) {
                signatures = signing.hasMultipleSigners()
                        ? signing.getApkContentsSigners()
                        : signing.getSigningCertificateHistory();
            }
        }
        if (signatures == null || signatures.length == 0) {
            signatures = info.signatures;
        }
        return signatures == null || signatures.length == 0
                ? null : signatures[0].toByteArray();
    }
}
