import pandas as pd
import sys
import argparse
from copy import deepcopy


CATEGORY_SEAT_COLS={
    "GEN":"GEN_Seats",
    "SC":"SC_Seats",
    "ST":"ST_Seats",
    "OBC-A":"OBC_A_Seats",
    "OBC-B":"OBC_B_Seats",
}

PREF_COLS=["Pref_1","Pref_2","Pref_3","Pref_4","Pref_5"]

def load_data(students_path:str,department_path:str):
    df_stu=pd.read_csv(students_path)
    df_dept=pd.read_csv(department_path)

    required_student_cols = {"Student_ID", "Name", "Category", "WBJEE_Rank", "WBJEE_Marks",
                              "Pref_1", "Pref_2", "Pref_3"}
    required_dept_cols    = {"Dept_ID", "Department_Name", "Total_Seats",
                              "GEN_Seats", "SC_Seats", "ST_Seats", "OBC_A_Seats", "OBC_B_Seats",
                              "Min_WBJEE_Marks"}
 
    missing_s = required_student_cols - set(df_stu.columns)
    missing_d = required_dept_cols    - set(df_dept.columns)
 
    if missing_s:
        raise ValueError(f"Students CSV is missing columns: {missing_s}")
    if missing_d:
        raise ValueError(f"Departments CSV is missing columns: {missing_d}")
    
    df_stu["Category"]=df_stu["Category"].str.strip().str.upper()

    return df_stu, df_dept


def build_seat_pool( df_dept: pd.DataFrame)->dict:
    pool={}
    for _, row in df_dept.iterrows():
        dept=row["Dept_ID"]
        pool[dept]={}
        for cat,col in CATEGORY_SEAT_COLS.items():
            pool[dept][cat]=int(row[col])
    return pool;


def allocate_seats(df_stu: pd.DataFrame , df_dept: pd.DataFrame ,pool: dict)->pd.DataFrame:
    min_marks=df_dept.set_index("Dept_ID")["Min_WBJEE_Marks"].to_dict()
    Dept_full_name=df_dept.set_index("Dept_ID")["Full_Name"].to_dict()

    sorted_students=df_stu.sort_values("WBJEE_Rank",ascending=True)

    results=[]
    for _, student in sorted_students.iterrows():
        sid       = student["Student_ID"]
        name      = student["Name"]
        category  = student["Category"]
        rank      = student["WBJEE_Rank"]
        marks     = student["WBJEE_Marks"]
 
        allocated      = False
        allocated_dept = None
        pref_number    = None
        remarks        = ""
 
        # Validate category
        if category not in CATEGORY_SEAT_COLS:
            results.append({
                "Student_ID": sid, "Name": name, "Category": category,
                "WBJEE_Rank": rank, "WBJEE_Marks": marks,
                "Allocated_Dept": None, "Allocated_Dept_Name": None,
                "Preference_Number": None, "Status": "Error",
                "Remarks": f"Unknown category '{category}'"
            })
            continue
 
        # Collect preferences (skip NaN / missing pref columns)
        prefs = []
        for col in PREF_COLS:
            if col in student.index and pd.notna(student[col]):
                prefs.append(str(student[col]).strip())
 
        for pref_idx, dept_id in enumerate(prefs, start=1):
            # 1. Does the department exist?
            if dept_id not in pool:
                continue  # skip invalid preference silently
 
            # 2. Eligibility: minimum marks check
            if dept_id in min_marks and marks < min_marks[dept_id]:
                continue  # not eligible for this dept
 
            # 3. Seat availability in own category
            if pool[dept_id].get(category, 0) > 0:
                pool[dept_id][category] -= 1
                allocated      = True
                allocated_dept = dept_id
                pref_number    = pref_idx
                remarks        = f"Category seat ({category})"
                break
 
            # 4. If own-category seats exhausted, try GEN pool (open category)
            #    Only applicable for reserved categories (SC/ST/OBC-A/OBC-B)
            #    In WBJEE: reserved candidates can fill GEN seats on merit
            if category != "GEN" and pool[dept_id].get("GEN", 0) > 0:
                # Check if student's rank is competitive enough for GEN seat
                # (simplified: if they reached this preference, assume merit)
                pool[dept_id]["GEN"] -= 1
                allocated      = True
                allocated_dept = dept_id
                pref_number    = pref_idx
                remarks        = f"Open/GEN seat (reserved candidate on merit)"
                break
 
        full_name = Dept_full_name.get(allocated_dept, allocated_dept) if allocated_dept else None
 
        results.append({
            "Student_ID":          sid,
            "Name":                name,
            "Category":            category,
            "WBJEE_Rank":          rank,
            "WBJEE_Marks":         marks,
            "Allocated_Dept":      allocated_dept,
            "Allocated_Dept_Name": full_name,
            "Preference_Number":   pref_number,
            "Status":              "Allocated" if allocated else "Unallocated",
            "Remarks":             remarks if allocated else "No seat available in any preference"
        })
 
    return pd.DataFrame(results)

def print_summary(results_df: pd.DataFrame, seat_pool: dict, df_dept: pd.DataFrame):
    """Print a console summary of the allocation round."""
    total      = len(results_df)
    allocated  = (results_df["Status"] == "Allocated").sum()
    unallocated= (results_df["Status"] == "Unallocated").sum()
    errors     = (results_df["Status"] == "Error").sum()
 
    print("\n" + "="*60)
    print("  WBJEE SEAT ALLOCATION — ROUND SUMMARY")
    print("="*60)
    print(f"  Total Students Processed : {total}")
    print(f"  Allocated                : {allocated}")
    print(f"  Unallocated              : {unallocated}")
    print(f"  Errors                   : {errors}")
    print(f"  Allocation Rate          : {allocated/total*100:.1f}%")
 
    print("\n--- Department-wise Allocation ---")
    dept_stats = (results_df[results_df["Status"] == "Allocated"]
                  .groupby("Allocated_Dept")
                  .size()
                  .reset_index(name="Allocated_Count"))
 
    dept_info = df_dept[["Dept_ID", "Department_Name", "Total_Seats"]].copy()
    dept_stats = dept_info.merge(dept_stats, left_on="Dept_ID", right_on="Allocated_Dept", how="left")
    dept_stats["Allocated_Count"] = dept_stats["Allocated_Count"].fillna(0).astype(int)
    dept_stats["Remaining_Seats"] = dept_stats["Total_Seats"] - dept_stats["Allocated_Count"]
    dept_stats["Fill_Rate_%"]     = (dept_stats["Allocated_Count"] / dept_stats["Total_Seats"] * 100).round(1)
 
    print(dept_stats[["Dept_ID", "Department_Name", "Total_Seats",
                       "Allocated_Count", "Remaining_Seats", "Fill_Rate_%"]]
          .to_string(index=False))
 
    print("\n--- Category-wise Allocation ---")
    cat_stats = (results_df.groupby(["Category", "Status"])
                 .size()
                 .unstack(fill_value=0)
                 .reset_index())
    print(cat_stats.to_string(index=False))
 
    print("\n--- Preference Satisfaction ---")
    alloc_df = results_df[results_df["Status"] == "Allocated"]
    pref_dist = alloc_df["Preference_Number"].value_counts().sort_index()
    for pref_num, count in pref_dist.items():
        print(f"  Got Preference {int(pref_num)}: {count} students ({count/allocated*100:.1f}%)")
 
    print("\n--- Remaining Seats in Pool ---")
    for dept, cats in seat_pool.items():
        total_rem = sum(cats.values())
        if total_rem > 0:
            print(f"  {dept}: {cats}")
    print("="*60 + "\n")
 
 
# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------
 
def main():
    parser = argparse.ArgumentParser(
        description="WBJEE Seat Allocation Algorithm",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("--students",    default="students.csv",
                        help="Path to students CSV (default: students.csv)")
    parser.add_argument("--departments", default="departments.csv",
                        help="Path to departments CSV (default: departments.csv)")
    parser.add_argument("--output",      default="allocation_results.csv",
                        help="Output CSV path (default: allocation_results.csv)")
    parser.add_argument("--no-summary",  action="store_true",
                        help="Suppress console summary")
 
    args = parser.parse_args()
 
    # --- Load ---
    print(f"Loading students from    : {args.students}")
    print(f"Loading departments from : {args.departments}")
    try:
        students_df, df_dept = load_data(args.students, args.departments)
    except (FileNotFoundError, ValueError) as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(1)
 
    print(f"\nStudents loaded  : {len(students_df)}")
    print(f"Departments loaded: {len(df_dept)}")
 
    # --- Build seat pool ---
    seat_pool = build_seat_pool(df_dept)
    original_pool = deepcopy(seat_pool)   # snapshot for reporting
 
    # --- Allocate ---
    print("\nRunning seat allocation...")
    results_df = allocate_seats(students_df, df_dept, seat_pool)
 
    # --- Save ---
    results_df.to_csv(args.output, index=False)
    print(f"Results saved to         : {args.output}")
 
    # --- Summary ---
    if not args.no_summary:
        print_summary(results_df, seat_pool, df_dept)
 
    return results_df
 
 
# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
 
if __name__ == "__main__":
    main()
 



