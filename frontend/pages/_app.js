import { AnimatePresence, motion } from "framer-motion";
import Head from "next/head";
import { useRouter } from "next/router";
import { Toaster } from "react-hot-toast";

import Footer from "@/components/Footer";
import Navbar from "@/components/Navbar";
import { EASE } from "@/lib/theme";
import { ConfigProvider } from "@/lib/useConfig";
import "@/styles/globals.css";

export default function App({ Component, pageProps }) {
  const router = useRouter();
  return (
    <ConfigProvider>
      <Head>
        <title>FactFlow — Rumours spread. Facts flow.</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
      </Head>
      <Navbar />
      <AnimatePresence mode="wait" initial={false}>
        <motion.main
          key={router.pathname}
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -20 }}
          transition={{ duration: 0.4, ease: EASE }}
          style={{ paddingTop: "var(--nav-height)" }}
        >
          <Component {...pageProps} />
        </motion.main>
      </AnimatePresence>
      <Footer />
      <Toaster
        position="bottom-center"
        toastOptions={{
          style: {
            background: "#111118",
            color: "#F0F0F5",
            border: "1px solid #2A2A3A",
            fontFamily: "var(--font-body)",
            fontSize: 14,
          },
        }}
      />
    </ConfigProvider>
  );
}
