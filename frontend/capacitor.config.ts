import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "com.traya.app",
  appName: "TRAYA",
  webDir: "dist",
  android: {
    allowMixedContent: true,
  },
  server: {
    cleartext: true,
  },
};

export default config;
