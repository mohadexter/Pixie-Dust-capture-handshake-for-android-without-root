package ma.pixiedust.app.usb;

import java.util.ArrayList;
import java.util.List;

/** The adapters the bundled driver stack knows how to bring up. */
public final class Adapters {

    public static final class Info {
        public final int vid;
        public final int pid;
        public final String chipset;
        public final String name;
        public final String bands;

        Info(int vid, int pid, String chipset, String name, String bands) {
            this.vid = vid;
            this.pid = pid;
            this.chipset = chipset;
            this.name = name;
            this.bands = bands;
        }

        public String vidPid() {
            return String.format("%04x:%04x", vid, pid);
        }
    }

    private static final List<Info> ALL = new ArrayList<>();

    static {
        // Ralink / MediaTek RT2xxx-RT5xxx
        ALL.add(new Info(0x148f, 0x5370, "RT5370", "Ralink RT5370", "2.4 GHz"));
        ALL.add(new Info(0x148f, 0x5372, "RT5372", "Ralink RT5372", "2.4/5 GHz"));
        ALL.add(new Info(0x148f, 0x5572, "RT5572", "Ralink RT5572 MIMO", "2.4/5 GHz"));
        ALL.add(new Info(0x148f, 0x3070, "RT3070", "Ralink RT3070 high power", "2.4 GHz"));
        ALL.add(new Info(0x148f, 0x2570, "RT2570", "Ralink RT2570 legacy", "2.4 GHz"));

        // MediaTek MT76xx / MT79xx
        ALL.add(new Info(0x0e8d, 0x7601, "MT7601U", "MediaTek MT7601U", "2.4 GHz"));
        ALL.add(new Info(0x148f, 0x7601, "MT7601U", "MediaTek MT7601U (Ralink id)", "2.4 GHz"));
        ALL.add(new Info(0x0e8d, 0x7610, "MT7610U", "MediaTek MT7610U AC600", "2.4/5 GHz"));
        ALL.add(new Info(0x0e8d, 0x7612, "MT7612U", "MediaTek MT7612U AC1200", "2.4/5 GHz"));
        ALL.add(new Info(0x0e8d, 0x7921, "MT7921AU", "MediaTek MT7921AU Wi-Fi 6", "2.4/5 GHz"));
        ALL.add(new Info(0x0e8d, 0x7925, "MT7925U", "MediaTek MT7925U Wi-Fi 7", "2.4/5/6 GHz"));

        // Atheros
        ALL.add(new Info(0x0cf3, 0x9271, "AR9271", "Atheros AR9271 (AWUS036NHA)", "2.4 GHz"));
        ALL.add(new Info(0x0cf3, 0x7015, "AR9271", "Atheros AR9271 variant", "2.4 GHz"));

        // Realtek
        ALL.add(new Info(0x0bda, 0x8187, "RTL8187", "Realtek RTL8187L", "2.4 GHz"));
        ALL.add(new Info(0x0bda, 0x8188, "RTL8188EUS", "Realtek RTL8188EUS", "2.4 GHz"));
        ALL.add(new Info(0x0bda, 0xf179, "RTL8188FTV", "Realtek RTL8188FTV", "2.4 GHz"));
        ALL.add(new Info(0x0bda, 0x8192, "RTL8192FU", "Realtek RTL8192FU", "2.4 GHz"));
        ALL.add(new Info(0x0bda, 0x8812, "RTL8812AU", "Realtek RTL8812AU (AWUS036ACH)", "2.4/5 GHz"));
        ALL.add(new Info(0x0bda, 0x8813, "RTL8814AU", "Realtek RTL8814AU AC1900", "2.4/5 GHz"));
        ALL.add(new Info(0x0bda, 0x8821, "RTL8821AU", "Realtek RTL8821AU AC600", "2.4/5 GHz"));
        ALL.add(new Info(0x0bda, 0x8822, "RTL8822BU", "Realtek RTL8822BU AC1200", "2.4/5 GHz"));
        ALL.add(new Info(0x0bda, 0x8922, "RTL8922AU", "Realtek RTL8922AU Wi-Fi 7", "2.4/5/6 GHz"));
        ALL.add(new Info(0x0bda, 0xc811, "RTL8811CU", "Realtek RTL8811CU AC600", "2.4/5 GHz"));
        ALL.add(new Info(0x0bda, 0xc822, "RTL8822CU", "Realtek RTL8822CU", "2.4/5 GHz"));

        // TP-Link
        ALL.add(new Info(0x2357, 0x0109, "RTL8192EU", "TP-Link TL-WN823N v2/v3", "2.4 GHz"));
        ALL.add(new Info(0x2357, 0x010c, "RTL8188EUS", "TP-Link TL-WN722N v2/v3", "2.4 GHz"));
        ALL.add(new Info(0x2357, 0x0137, "Archer T2U Plus", "TP-Link Archer T2U Plus", "2.4/5 GHz"));
    }

    private Adapters() {
    }

    public static List<Info> all() {
        return ALL;
    }

    public static Info find(int vid, int pid) {
        for (Info info : ALL) {
            if (info.vid == vid && info.pid == pid) {
                return info;
            }
        }
        return null;
    }

    public static List<String> chipsets() {
        List<String> out = new ArrayList<>();
        for (Info info : ALL) {
            if (!out.contains(info.chipset)) {
                out.add(info.chipset);
            }
        }
        return out;
    }
}
