"use client";

/**
 * payment-year-context.tsx
 *
 * Global payment-year selector.
 * - Defaults to the current calendar year.
 * - Persisted to localStorage so the selection survives page refreshes.
 * - Exported hook: usePaymentYear()
 *
 * TODO: migrate individual pages (analysis, submissions, reports …) to read
 * paymentYear from this context instead of maintaining local useState.
 */

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  ReactNode,
} from "react";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const LS_KEY = "raf_payment_year";
const CURRENT_YEAR = new Date().getFullYear();
/** Years shown in the PY selector: current year and the two prior years. */
export const PAYMENT_YEARS: number[] = [
  CURRENT_YEAR,
  CURRENT_YEAR - 1,
  CURRENT_YEAR - 2,
];

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PaymentYearContextType {
  paymentYear: number;
  setPaymentYear: (year: number) => void;
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const PaymentYearContext = createContext<PaymentYearContextType | undefined>(
  undefined
);

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function PaymentYearProvider({ children }: { children: ReactNode }) {
  const [paymentYear, setPaymentYearState] = useState<number>(() => {
    if (typeof window === "undefined") return CURRENT_YEAR;
    const stored = localStorage.getItem(LS_KEY);
    const parsed = stored ? parseInt(stored, 10) : NaN;
    return PAYMENT_YEARS.includes(parsed) ? parsed : CURRENT_YEAR;
  });

  // Sync to localStorage on every change.
  useEffect(() => {
    try {
      localStorage.setItem(LS_KEY, String(paymentYear));
    } catch {
      // localStorage may be unavailable in certain browser contexts.
    }
  }, [paymentYear]);

  const setPaymentYear = useCallback((year: number) => {
    if (PAYMENT_YEARS.includes(year)) {
      setPaymentYearState(year);
    }
  }, []);

  return (
    <PaymentYearContext.Provider value={{ paymentYear, setPaymentYear }}>
      {children}
    </PaymentYearContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function usePaymentYear(): PaymentYearContextType {
  const ctx = useContext(PaymentYearContext);
  if (ctx === undefined) {
    throw new Error("usePaymentYear must be used within a PaymentYearProvider");
  }
  return ctx;
}
