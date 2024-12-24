import fileinput
import multiprocessing
import os
import shutil
import time
from shutil import copy2

from google.cloud import storage

from sfkit.api import get_doc_ref_dict, update_firestore, website_send_file
from sfkit.utils import constants
from sfkit.utils.helper_functions import (copy_results_to_cloud_storage,
                                          copy_to_out_folder, plot_assoc,
                                          postprocess_assoc, run_command)
from sfkit.utils.sfgwas_helper_functions import boot_sfkit_proxy
from sfkit.utils.sfgwas_protocol import update_config_global


def run_dti_protocol(role: str, demo: bool = False) -> None:
    print("\n\n Begin running Secure DTI protocol \n\n")
    if not demo:
        update_parameters(role)
        ## connect_to_other_vms(role)
        # prepare_data(constants.ENCRYPTED_DATA_FOLDER, role)
        # copy_data_to_gwas_repo(constants.ENCRYPTED_DATA_FOLDER, role)
        sync_with_other_vms(role)
        update_config_global(network_only=True)
    start_datasharing(role, demo)
    sync_with_other_vms(role)
    start_dti(role, demo)
    # start_gwas(role, demo)


def update_parameters(role: str) -> None:
    par_file = f"{constants.EXECUTABLES_PREFIX}secure-dti/mpc/par/test.par.{role}.txt"
    print(f"\n\n Updating parameters in '{par_file}'\n\n")

    doc_ref_dict = get_doc_ref_dict()

    # shared parameters and advanced parameters
    pars = {**doc_ref_dict["parameters"], **doc_ref_dict["advanced_parameters"]}

    # individual parameters
    # for i in range(1, len(doc_ref_dict["participants"])):
    #     pars[f"NUM_INDS_SP_{i}"] = doc_ref_dict["personal_parameters"][doc_ref_dict["participants"][i]]["NUM_INDS"]

    # pars["NUM_INDS"] = {"value": ""}
    # pars["NUM_INDS"]["value"] = str(int(pars["NUM_INDS_SP_1"]["value"]) + int(pars["NUM_INDS_SP_2"]["value"]))

    # num threads = num_cpus = $(nproc)
    num_cpus = str(multiprocessing.cpu_count())
    pars["NUM_THREADS"] = {"value": num_cpus}
    update_firestore(f"update_firestore::NUM_THREADS={num_cpus}")
    update_firestore(f"update_firestore::NUM_CPUS={num_cpus}")

    # update pars with ipaddresses and ports
    for i in range(len(doc_ref_dict["participants"])):
        ip = doc_ref_dict["personal_parameters"][doc_ref_dict["participants"][i]]["IP_ADDRESS"]["value"]
        while ip == "":
            print(f"IP address for {doc_ref_dict['participants'][i]} is empty. Waiting...")
            time.sleep(5)

            doc_ref_dict = get_doc_ref_dict()
            ip = doc_ref_dict["personal_parameters"][doc_ref_dict["participants"][i]]["IP_ADDRESS"]["value"]

        pars[f"IP_ADDR_P{i}"] = {"value": ip}

        ports = doc_ref_dict["personal_parameters"][doc_ref_dict["participants"][i]]["PORTS"]["value"]
        for j in range(i + 1, 4):
            pars[f"PORT_P{i}_P{j}"] = {"value": ports.split(",")[j]}

    # update file paths
    data_path = _get_data_path(role)
    pars["FEATURES_FILE"] = {"value": f"{data_path}/X"}
    pars["LABELS_FILE"] = {"value": f"{data_path}/y"}
    pars["TRAIN_SUFFIXES"] = {"value": f"{data_path}/train_suffixes.txt"}
    pars["TEST_SUFFIXES"] = {"value": f"{data_path}/test_suffixes.txt"}

    # update par file
    for line in fileinput.input(par_file, inplace=True):
        key = str(line).split(" ")[0]
        if key in pars:
            line = f"{key} " + str(pars[key]["value"]) + "\n"
        print(line, end="")


def _get_data_path(role: str) -> str:
    data_path = ''
    with open(os.path.join(constants.SFKIT_DIR, "data_path.txt"), "r") as f:
        data_path = f.readline().rstrip()
    return data_path

# def prepare_data(data_path: str, role: str) -> None:
#     doc_ref_dict: dict = get_doc_ref_dict()
#     study_title: str = doc_ref_dict["title"]

#     if role == "0":
#         os.makedirs(data_path, exist_ok=True)
#         storage.Client().bucket("sfkit").blob(f"{study_title}/pos.txt").download_to_filename(f"{data_path}/pos.txt")


# def copy_data_to_gwas_repo(
#     data_path: str, role: str
# ) -> None:  # TODO: change the path in parameter file instead? Or move instead of copy?
#     print("\n\n Copy data to GWAS repo \n\n")
#     files_to_copy = ["g.bin", "m.bin", "p.bin", "other_shared_key.bin", "pos.txt"] if role != "0" else ["pos.txt"]
#     for file_name in files_to_copy:
#         src_file_path = os.path.join(data_path, file_name)
#         dest_file_path = os.path.join("secure-gwas/test_data", file_name)
#         copy2(src_file_path, dest_file_path)
#     print("\n\n Finished copying data to GWAS repo \n\n")


def sync_with_other_vms(role: str) -> None:
    update_firestore("update_firestore::status=syncing up")
    update_firestore("update_firestore::task=Syncing up machines")
    print("Begin syncing up")
    # wait until all participants have the status of starting data sharing protocol
    while True:
        doc_ref_dict: dict = get_doc_ref_dict()
        statuses = doc_ref_dict["status"].values()
        if all(status == "syncing up" for status in statuses):
            break
        print("Waiting for all participants to sync up...")
        time.sleep(5)
    print("Finished syncing up")


def _get_par_path(role: str, demo: bool) -> str:
    return f"../par/{'demo' if demo else 'test'}.par.{role}.txt"


def start_datasharing(role: str, demo: bool) -> None:
    update_firestore("update_firestore::task=Performing data sharing protocol")
    print("\n\n starting data sharing protocol \n\n")

    cwd = os.getcwd()
    command = []
    sfkit_proxy = None
    if constants.SFKIT_PROXY_ON:
        sfkit_proxy = boot_sfkit_proxy(role=role)

        proxychains_conf = os.path.join(cwd, "proxychains.conf")
        copy2("/etc/proxychains.conf", proxychains_conf)
        for line in fileinput.input(proxychains_conf, inplace=True):
            if line.startswith("socks"):
                line = f"socks5 127.0.0.1 {constants.SFKIT_PROXY_PORT}\n"
            print(line, end="")
        command += ["proxychains", "-f", proxychains_conf]

    command += ["bin/ShareData", role, _get_par_path(role, demo)]
    if role == "3":
        command.append(_get_data_path(role))


    os.chdir(f"{constants.EXECUTABLES_PREFIX}secure-dti/mpc/code")
    run_command(command, fail_message="Failed Secure-DTI data sharing protocol")
    os.chdir(cwd)

    if sfkit_proxy:
        sfkit_proxy.terminate()

    print("\n\n Finished data sharing protocol\n\n")


def start_dti(role: str, demo: bool) -> None:
    update_firestore("update_firestore::task=Performing DTI protocol")
    print("\n\n starting DTI \n\n")
    update_firestore("update_firestore::status=starting DTI")

    cwd = os.getcwd()
    command = []
    if constants.SFKIT_PROXY_ON:
        boot_sfkit_proxy(role=role)

        proxychains_conf = os.path.join(cwd, "proxychains.conf")
        command += ["proxychains", "-f", proxychains_conf]

    command += ["bin/TrainSecureDTI", role, _get_par_path(role, demo)]

    if int(role) < 3:
        os.chdir(f"{constants.EXECUTABLES_PREFIX}secure-dti/mpc/code")
        run_command(command, fail_message="Failed Secure-DTI protocol")
    os.chdir(cwd)

    print("\n\n Finished DTI \n\n")

#     if role != "0":
#         process_output_files(role, demo)

#     update_firestore("update_firestore::status=Finished protocol!")


# def process_output_files(role: str, demo: bool) -> None:
#     # sourcery skip: assign-if-exp, introduce-default-else, swap-if-expression
#     doc_ref_dict = get_doc_ref_dict()
#     num_inds_total = 1_000
#     if not demo:
#         num_inds_total = sum(
#             int(doc_ref_dict["personal_parameters"][user]["NUM_INDS"]["value"])
#             for user in doc_ref_dict["participants"]
#         )
#     num_covs = int(doc_ref_dict["parameters"]["NUM_COVS"]["value"])

#     postprocess_assoc(
#         f"{constants.EXECUTABLES_PREFIX}secure-gwas/out/new_assoc.txt",
#         f"{constants.EXECUTABLES_PREFIX}secure-gwas/out/test_assoc.txt",
#         f"{constants.EXECUTABLES_PREFIX}secure-gwas/test_data/pos.txt",
#         f"{constants.EXECUTABLES_PREFIX}secure-gwas/out/test_gkeep1.txt",
#         f"{constants.EXECUTABLES_PREFIX}secure-gwas/out/test_gkeep2.txt",
#         num_inds_total,
#         num_covs,
#     )
#     plot_assoc(
#         f"{constants.EXECUTABLES_PREFIX}secure-gwas/out/manhattan.png",
#         f"{constants.EXECUTABLES_PREFIX}secure-gwas/out/new_assoc.txt",
#     )

#     doc_ref_dict: dict = get_doc_ref_dict()
#     user_id: str = doc_ref_dict["participants"][int(role)]

#     relevant_paths = [f"{constants.EXECUTABLES_PREFIX}secure-gwas/out"]
#     copy_to_out_folder(relevant_paths)

#     if results_path := doc_ref_dict["personal_parameters"][user_id].get("RESULTS_PATH", {}).get("value", ""):
#         copy_results_to_cloud_storage(role, results_path, f"{constants.EXECUTABLES_PREFIX}secure-gwas/out")

#     send_results: str = doc_ref_dict["personal_parameters"][user_id].get("SEND_RESULTS", {}).get("value")
#     if send_results == "Yes":
#         with open(f"{constants.EXECUTABLES_PREFIX}secure-gwas/out/new_assoc.txt", "r") as file:
#             website_send_file(file, "new_assoc.txt")

#         with open(f"{constants.EXECUTABLES_PREFIX}secure-gwas/out/manhattan.png", "rb") as file:
#             website_send_file(file, "manhattan.png")
