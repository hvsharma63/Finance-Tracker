import { fmtDate, inr, minorToInput, parseRupees } from "./format";

describe("inr", () => {
  it("uses Indian digit grouping from integer paise", () => {
    expect(inr(12345678)).toBe("₹1,23,456.78");
    expect(inr(10000000000)).toBe("₹10,00,00,000.00");
    expect(inr(-50000)).toBe("-₹500.00");
    expect(inr(5)).toBe("₹0.05");
    expect(inr(null)).toBe("—");
  });
  it("compacts large values to lakh/crore", () => {
    expect(inr(25_00_000_00, { compact: true })).toBe("₹25.00 L");
    expect(inr(3_50_00_000_00, { compact: true })).toBe("₹3.50 Cr");
  });
});

describe("parseRupees", () => {
  it("parses without floating point error", () => {
    expect(parseRupees("0.29")).toBe(29);
    expect(parseRupees("1,23,456.78")).toBe(12345678);
    expect(parseRupees("-500")).toBe(-50000);
    expect(parseRupees("12.345")).toBeNull();
    expect(parseRupees("abc")).toBeNull();
  });
  it("round-trips with minorToInput", () => {
    for (const v of [0, 1, -1, 12345678, -999]) expect(parseRupees(minorToInput(v))).toBe(v);
  });
});

it("formats dates day-first", () => {
  expect(fmtDate("2026-04-05")).toBe("05 Apr 2026");
});
