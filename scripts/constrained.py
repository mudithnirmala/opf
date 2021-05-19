#!/usr/bin/pythonimport comet_mlimport pytorch_lightning as plfrom pytorch_lightning.loggers import CometLoggerfrom torch.utils.data import Dataset, random_split, TensorDatasetimport numpy as npimport torchimport argparsefrom alegnn.utils import graphToolsfrom alegnn.modules.architectures import SelectionGNNfrom pyopf.data import load_datafrom pyopf.modules import OPFLogBarrierfrom pyopf.power import load_case, NetworkManagertorch.autograd.set_detect_anomaly(True)parser = argparse.ArgumentParser(description='Train unsupervised OPF model.')parser.add_argument('--job', action="store_true",                    help="Indicated that this is a job running in the background that will dump its output to a file. "                         "Will limit console output from progress bars.")args = parser.parse_args()# Constantsdata_dir = "./data"ratio_train = 0.8device = torch.device("cpu")dtype = torch.float32F0 = 2isjob = args.job# Meta-parametersA_scaling = 0.001A_threshold = 0.01case = "case30"# instantiate the NetworkManagermanager = NetworkManager(load_case(case, data_dir), A_scaling, A_threshold)N = manager.n_buses# Parameters / Configurationparam = {    "train": dict(        max_epochs=20,        batch_size=256,    ),    "gnn": dict(        dimLayersMLP=[4 * N],        dimNodeSignals=[F0, 64],        nFilterTaps=[4],        poolingSize=[1],        nSelectedNodes=[N]    ),    "barrier": dict(        type="relaxed_log",  # log, relaxed_log        t=200,  # higher -> better approximation to barrier        s=100,  # the slope at which the barrier becomes linear        cost_weight=0.01,    ),    "meta": dict(        A_scaling=A_scaling,        A_threshold=A_threshold,        model="selection",        case=case    ),}# Prepare graph shift operatoradjacencyMatrix = manager.get_adjacency()G = graphTools.Graph("adjacency", adjacencyMatrix.shape[0], {"adjacencyMatrix": adjacencyMatrix})G.computeGFT()S, order = graphTools.permDegree(G.S / np.max(np.real(G.E)))  # normalize GSO by dividing by largest e-value# Load data and convert from numpy to torch tensors.train_samples, test_samples, test_labels = load_data(case, data_dir)train_data = TensorDataset(torch.from_numpy(train_samples).to(device))test_data = TensorDataset(torch.from_numpy(test_samples).to(device), torch.from_numpy(test_labels).to(device))train_split = int(len(train_data) * ratio_train)val_split = len(train_data) - train_splittrain_data, val_data = random_split(train_data, [train_split, val_split])def collate_fn(batch):    return tuple([torch.stack(item).to(device).to(torch.float32) for item in zip(*batch)])train_loader = torch.utils.data.DataLoader(train_data, batch_size=param["train"]["batch_size"], shuffle=True,                                           collate_fn=collate_fn)val_loader = torch.utils.data.DataLoader(val_data, batch_size=param["train"]["batch_size"],                                         collate_fn=collate_fn)test_loader = torch.utils.data.DataLoader(test_data, batch_size=param["train"]["batch_size"],                                          collate_fn=collate_fn)gnn = SelectionGNN(GSO=S, **param["gnn"]).to(dtype).to(device)barrier = OPFLogBarrier(manager, gnn, **param["barrier"])logger = CometLogger(workspace="damowerko", project_name="opf", save_dir="./logs")logger.log_hyperparams(param)logger.experiment.log_code(folder="./pyopf")logger.experiment.log_code(folder="./scripts")logger.experiment.set_model_graph(str(barrier))trainer = pl.Trainer(logger=logger, progress_bar_refresh_rate=(0 if isjob else 1))trainer.fit(barrier, train_loader, val_loader)