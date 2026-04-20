# bubble sort implementation with a simple test

def bubble_sort(arr):
    """Return a new list containing the elements of *arr* sorted in ascending order using bubble sort.

    The algorithm repeatedly steps through the list, compares adjacent items and swaps them
    if they are in the wrong order. This continues until a complete pass produces no swaps.
    The implementation returns a **new** list so the original input is not mutated.
    """
    # Work on a copy to avoid side‑effects on the caller's list
    a = list(arr)
    n = len(a)
    # Perform n‑1 passes; after each pass the largest remaining element is at its final position
    for i in range(n - 1):
        swapped = False
        # Last i elements are already sorted, so we can ignore them
        for j in range(n - 1 - i):
            if a[j] > a[j + 1]:
                a[j], a[j + 1] = a[j + 1], a[j]
                swapped = True
        # If no swaps occurred, the list is already sorted and we can stop early
        if not swapped:
            break
    return a

# Simple demonstration / informal test when run directly
if __name__ == "__main__":
    examples = [
        [],
        [1],
        [5, 2, 9, 1, 5, 6],
        [3, 2, 1],
        [1, 2, 3, 4],
    ]
    for ex in examples:
        print(f"original: {ex} -> sorted: {bubble_sort(ex)}")
