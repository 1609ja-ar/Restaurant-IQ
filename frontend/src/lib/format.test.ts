import { describe, expect, it } from "vitest";
import { fmtCompact, fmtInt, fmtKpi, fmtMoney, fmtRating, NA } from "./format";
import { activeFilterCount, EMPTY_FILTERS, filtersToParams } from "./filters";
import { buildQuery } from "./api";

describe("format", () => {
  it("shows N/A for missing values, never 0", () => {
    expect(fmtRating(null)).toBe(NA);
    expect(fmtMoney(undefined, "INR")).toBe(NA);
    expect(fmtInt(NaN)).toBe(NA);
  });
  it("keeps real zeros", () => {
    expect(fmtInt(0)).toBe("0");
    expect(fmtMoney(0, "USD")).toBe("$0");
  });
  it("formats currency and ratings", () => {
    expect(fmtMoney(120000, "INR")).toBe("₹1,20,000");
    expect(fmtMoney(25, "XYZ")).toBe("25 XYZ");
    expect(fmtRating(3.94945)).toBe("3.95");
    expect(fmtKpi(4.1, "/5", false)).toBe("4.10");
  });
  it("compacts axis numbers", () => {
    expect(fmtCompact(1500)).toBe("1.5k");
    expect(fmtCompact(2000000)).toBe("2M");
  });
});

describe("filters", () => {
  it("serializes repeated params and skips unset values", () => {
    const f = { ...EMPTY_FILTERS, location: ["HSR", "BTM"], online_order: false };
    expect(buildQuery(filtersToParams(f))).toBe("?location=HSR&location=BTM&online_order=false");
    expect(activeFilterCount(f)).toBe(3);
    expect(buildQuery(filtersToParams(EMPTY_FILTERS))).toBe("");
  });
});
