import { describe, it, expect } from "vitest";
import { asRowList } from "./utils";

describe("asRowList", () => {
  it("returns arrays unchanged", () => {
    expect(asRowList([1, 2])).toEqual([1, 2]);
  });

  it("unwraps { rows: [...] } wrappers", () => {
    expect(asRowList({ rows: [{ id: 1 }] })).toEqual([{ id: 1 }]);
  });

  it("returns [] for nullish and non-table objects", () => {
    expect(asRowList(null)).toEqual([]);
    expect(asRowList(undefined)).toEqual([]);
    expect(asRowList({ foo: 1 })).toEqual([]);
  });
});
