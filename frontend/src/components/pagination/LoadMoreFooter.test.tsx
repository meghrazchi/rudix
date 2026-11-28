import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LoadMoreFooter } from "@/components/pagination/LoadMoreFooter";
import { PickerSearchInput } from "@/components/pagination/PickerSearchInput";

describe("LoadMoreFooter", () => {
  it("shows the count and loads more on click", async () => {
    const onLoadMore = vi.fn();
    render(
      <LoadMoreFooter
        shown={20}
        total={45}
        hasMore
        isLoadingMore={false}
        onLoadMore={onLoadMore}
        searchHint
      />,
    );

    expect(screen.getByText(/Showing 20 of 45/)).toBeInTheDocument();
    expect(screen.getByText(/Search to find more/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(onLoadMore).toHaveBeenCalledTimes(1);
  });

  it("announces loading and disables the button", () => {
    render(
      <LoadMoreFooter
        shown={20}
        total={45}
        hasMore
        isLoadingMore
        onLoadMore={vi.fn()}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent("Loading more…");
    expect(
      screen.getByRole("button", { name: "Loading more…" }),
    ).toBeDisabled();
  });

  it("hides the button when everything is loaded and uses the row count without a total", () => {
    render(
      <LoadMoreFooter
        shown={3}
        total={null}
        hasMore={false}
        isLoadingMore={false}
        onLoadMore={vi.fn()}
      />,
    );

    expect(screen.getByText("Showing 3 of 3")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows no count while the total is unknown and more rows exist", () => {
    render(
      <LoadMoreFooter
        shown={3}
        total={null}
        hasMore
        isLoadingMore={false}
        onLoadMore={vi.fn()}
      />,
    );
    expect(screen.getByTestId("load-more-count")).toHaveTextContent("");
  });
});

describe("PickerSearchInput", () => {
  it("reports typed values", async () => {
    const onChange = vi.fn();
    render(
      <PickerSearchInput
        value=""
        onChange={onChange}
        placeholder="Filter"
        ariaLabel="Search collections"
      />,
    );
    await userEvent.type(screen.getByLabelText("Search collections"), "a");
    expect(onChange).toHaveBeenCalledWith("a");
  });
});
