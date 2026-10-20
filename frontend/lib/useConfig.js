import { createContext, createElement, useContext, useEffect, useState } from "react";

import { getPublicConfig } from "@/lib/api";

const ConfigContext = createContext(null);

/** Loads /api/config once and shares it (models, provider, evidence sources, frontend URL). */
export function ConfigProvider({ children }) {
  const [config, setConfig] = useState(null);

  useEffect(() => {
    getPublicConfig()
      .then(setConfig)
      .catch(() => setConfig({ unavailable: true }));
  }, []);

  return createElement(ConfigContext.Provider, { value: config }, children);
}

/** Public backend configuration, or null while loading. */
export function useConfig() {
  return useContext(ConfigContext);
}
