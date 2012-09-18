import os

import openbabel
import cclib.parser
import logging
from subprocess import Popen

from qmdata import CCLibData
from molecule import QMMolecule
from reaction import QMReaction

class Gaussian:
    """
    A base class for all QM calculations that use Gaussian.
    
    Classes such as :class:`GaussianMol` will inherit from this class.
    """
    
    inputFileExtension = '.gjf'
    outputFileExtension = '.out'
    executablePath = os.path.join(os.getenv('GAUSS_EXEDIR', default="$g09root/g09") , 'g09')

    usePolar = False
    
    #: List of phrases that indicate failure
    #: NONE of these must be present in a succesful job.
    failureKeys = [
                   'ERROR TERMINATION',
                   'IMAGINARY FREQUENCIES'
                   ]
    
    #: List of phrases to indicate success.
    #: ALL of these must be present in a successful job.
    successKeys = [
                   'Normal termination of Gaussian'
                  ]
    
    def run(self):
        # submits the input file to Gaussian
        process = Popen([self.executablePath, self.inputFilePath, self.outputFilePath])
        process.communicate()# necessary to wait for executable termination!
        
        return self.verifyOutputFile()
        
    def verifyOutputFile(self):
        """
        Check's that an output file exists and was successful.
        
        Returns a boolean flag that states whether a successful GAUSSIAN simulation already exists for the molecule with the 
        given (augmented) InChI Key.
        
        The definition of finding a successful simulation is based on these criteria:
        1) finding an output file with the file name equal to the InChI Key
        2) NOT finding any of the keywords that are denote a calculation failure
        3) finding all the keywords that denote a calculation success.
        4) finding a match between the InChI of the given molecule and the InchI found in the calculation files
        
        If any of the above criteria is not matched, False will be returned and the procedures to start a new calculation 
        will be initiated.
        """
        if not os.path.exists(self.outputFilePath):
            logging.info("Output file {0} does not exist.".format(self.outputFilePath))
            return False
    
        InChIMatch=False #flag (1 or 0) indicating whether the InChI in the file matches InChIaug this can only be 1 if InChIFound is also 1
        InChIFound=False #flag (1 or 0) indicating whether an InChI was found in the log file
        
        # Initialize dictionary with "False"s 
        successKeysFound = dict([(key, False) for key in self.successKeys])
        
        with open(self.outputFilePath) as outputFile:
            for line in outputFile:
                line = line.strip()
                
                for element in self.failureKeys: #search for failure keywords
                    if element in line:
                        logging.error("Gaussian output file contains the following error: {0}".format(element) )
                        return False
                    
                for element in self.successKeys: #search for success keywords
                    if element in line:
                        successKeysFound[element] = True
               
                if line.startswith("InChI="):
                    logFileInChI = line #output files should take up to 240 characters of the name in the input file
                    InChIFound = True
                    if logFileInChI == self.geometry.uniqueIDlong:
                        InChIMatch = True
                    elif self.geometry.uniqueIDlong.startswith(logFileInChI):
                        logging.info("InChI too long to check, but beginning matches so assuming OK.")
                        InChIMatch = True
                    else:
                        logging.info("InChI in log file didn't match that in geometry.")
                        logging.info(self.geometry.uniqueIDlong)
                        logging.info(logFileInChI)
        
        # Check that ALL 'success' keywords were found in the file.
        if not all( successKeysFound.values() ):
            logging.error('Not all of the required keywords for sucess were found in the output file!')
            return False
        
        if not InChIFound:
            logging.error("No InChI was found in the Gaussian output file {0}".format(self.outputFilePath))
            return False
        
        if InChIMatch:
            logging.info("Successful Gaussian quantum result found in {0}".format(self.outputFilePath))
            # " + self.molfile.name + " ("+self.molfile.InChIAug+") has been found. This log file will be used.")
            return True
        else:
            return False # until the next line works
        
        #InChIs do not match (most likely due to limited name length mirrored in log file (240 characters), but possibly due to a collision)
        return self.checkForInChiKeyCollision(logFileInChI) # Not yet implemented!
        
    def parse(self):
        """
        Parses the results of the Gaussian calculation, and returns a CCLibData object.
        """
        parser = cclib.parser.Gaussian(self.outputFilePath)
        parser.logger.setLevel(logging.ERROR) #cf. http://cclib.sourceforge.net/wiki/index.php/Using_cclib#Additional_information
        cclibData = parser.parse()
        radicalNumber = sum([i.radicalElectrons for i in self.molecule.atoms])
        qmData = CCLibData(cclibData, radicalNumber+1)
        return qmData
    
    
    
class GaussianMol(QMMolecule, Gaussian):
    """
    A base Class for calculations of molecules using Gaussian. 
    
    Inherits from both :class:`QMMolecule` and :class:`Gaussian`.
    """
    
    def writeInputFile(self, attempt):
        """
        Using the :class:`Geometry` object, write the input file
        for the `attmept`th attempt.
        """
    
        obConversion = openbabel.OBConversion()
        obConversion.SetInAndOutFormats("mol", "gjf")
        mol = openbabel.OBMol()
    
        obConversion.ReadFile(mol, self.getMolFilePathForCalculation(attempt) )
    
        mol.SetTitle(self.geometry.uniqueIDlong)
        obConversion.SetOptions('k', openbabel.OBConversion.OUTOPTIONS)
        input_string = obConversion.WriteString(mol)
        top_keys = self.inputFileKeywords(attempt)
        with open(self.inputFilePath, 'w') as gaussianFile:
            gaussianFile.write(top_keys)
            gaussianFile.write(input_string)
            gaussianFile.write('\n')
            if self.usePolar:
                gaussianFile.write('\n\n\n')
                gaussianFile.write(polar_keys)
    
    def inputFileKeywords(self, attempt):
        """
        Return the top keywords.
        """
        raise NotImplementedError("Should be defined by subclass, eg. GaussianMolPM3")
    
    def generateQMData(self):
        """
        Calculate the QM data and return a QMData object.
        """
        self.createGeometry()
        if self.verifyOutputFile():
            logging.info("Found a successful output file already; using that.")
        else:
            success = False
            for attempt in range(1, self.maxAttempts+1):
                self.writeInputFile(attempt)
                success = self.run()
                if success:
                    logging.info('Attempt {0} of {1} on species {2} succeeded.'.format(attempt, self.maxAttempts, self.molecule.toAugmentedInChI()))
                    break
            else:
                raise Exception('QM thermo calculation failed for {0}.'.format(self.molecule.toAugmentedInChI()))
        result = self.parse() # parsed in cclib
        return result
    


class GaussianMolPM3(GaussianMol):

    #: Keywords that will be added at the top of the qm input file
    keywords = [
               "# pm3 opt=(verytight,gdiis) freq IOP(2/16=3)",
               "# pm3 opt=(verytight,gdiis) freq IOP(2/16=3) IOP(4/21=2)",
               "# pm3 opt=(verytight,calcfc,maxcyc=200) freq IOP(2/16=3) nosymm" ,
               "# pm3 opt=(verytight,calcfc,maxcyc=200) freq=numerical IOP(2/16=3) nosymm",
               "# pm3 opt=(verytight,gdiis,small) freq IOP(2/16=3)",
               "# pm3 opt=(verytight,nolinear,calcfc,small) freq IOP(2/16=3)",
               "# pm3 opt=(verytight,gdiis,maxcyc=200) freq=numerical IOP(2/16=3)",
               "# pm3 opt=tight freq IOP(2/16=3)",
               "# pm3 opt=tight freq=numerical IOP(2/16=3)",
               "# pm3 opt=(tight,nolinear,calcfc,small,maxcyc=200) freq IOP(2/16=3)",
               "# pm3 opt freq IOP(2/16=3)",
               "# pm3 opt=(verytight,gdiis) freq=numerical IOP(2/16=3) IOP(4/21=200)",
               "# pm3 opt=(calcfc,verytight,newton,notrustupdate,small,maxcyc=100,maxstep=100) freq=(numerical,step=10) IOP(2/16=3) nosymm",
               "# pm3 opt=(tight,gdiis,small,maxcyc=200,maxstep=100) freq=numerical IOP(2/16=3) nosymm",
               "# pm3 opt=(tight,gdiis,small,maxcyc=200,maxstep=100) freq=numerical IOP(2/16=3) nosymm",
               "# pm3 opt=(verytight,gdiis,calcall,small,maxcyc=200) IOP(2/16=3) IOP(4/21=2) nosymm",
               "# pm3 opt=(verytight,gdiis,calcall,small) IOP(2/16=3) nosymm",
               "# pm3 opt=(calcall,small,maxcyc=100) IOP(2/16=3)",
               ]

    @property
    def scriptAttempts(self):
        "The number of attempts with different script keywords"
        return len(self.keywords)

    @property
    def maxAttempts(self):
        "The total number of attempts to try"
        return 2 * len(self.keywords)

    def inputFileKeywords(self, attempt):
        """
        Return the top keywords for attempt number `attempt`.

        NB. `attempt`s begin at 1, not 0.
        """
        assert attempt <= self.maxAttempts
        if attempt > self.scriptAttempts:
            attempt -= self.scriptAttempts
        return self.keywords[attempt-1]
        
        
class GaussianReaction(QMReaction, Gaussian):
    """
    A base Class for calculations of molecules using Gaussian. 
    
    Inherits from both :class:`QMReaction` and :class:`Gaussian`.
    """
    def writeInputFile(self, attempt):
        """
        Using the :class:`Geometry` object, write the input file
        for the `attmept`th attempt.
        """
    
        obConversion = openbabel.OBConversion()
        obConversion.SetInAndOutFormats("mol", "gjf")
        mol = openbabel.OBMol()
    
        obConversion.ReadFile(mol, self.getMolFilePathForCalculation(attempt) )
    
        mol.SetTitle(self.geometry.uniqueIDlong)
        obConversion.SetOptions('k', openbabel.OBConversion.OUTOPTIONS)
        input_string = obConversion.WriteString(mol)
        top_keys = self.inputFileKeywords(attempt)
        with open(self.inputFilePath, 'w') as gaussianFile:
            gaussianFile.write(top_keys)
            gaussianFile.write(input_string)
            gaussianFile.write('\n')
            if self.usePolar:
                gaussianFile.write('\n\n\n')
                gaussianFile.write(polar_keys)
    
    def inputFileKeywords(self, attempt):
        """
        Return the top keywords.
        """
        raise NotImplementedError("Should be defined by subclass, eg. GaussianMolPM3")
    
    def generateKineticData(self):
        """
        Calculate the QM data and return a QMData object.
        """
        import ipdb; ipdb.set_trace()
        self.generateTSEstimate()
        import ipdb; ipdb.set_trace()
        if self.verifyOutputFile():
            logging.info("Found a successful output file already; using that.")
        else:
            success = False
            for attempt in range(1, self.maxAttempts+1):
                self.writeInputFile(attempt)
                success = self.run()
                if success:
                    logging.info('Attempt {0} of {1} on species {2} succeeded.'.format(attempt, self.maxAttempts, self.molecule.toAugmentedInChI()))
                    break
            else:
                raise Exception('QM thermo calculation failed for {0}.'.format(self.molecule.toAugmentedInChI()))
        result = self.parse() # parsed in cclib
        return result


class GaussianReactionPM3(GaussianReaction):
    #: Keywords that will be added at the top of the qm input file
    keywords = [
               "# pm3 opt=(verytight,gdiis) freq IOP(2/16=3)",
               "# pm3 opt=(verytight,gdiis) freq IOP(2/16=3) IOP(4/21=2)",
               "# pm3 opt=(verytight,calcfc,maxcyc=200) freq IOP(2/16=3) nosymm" ,
               "# pm3 opt=(verytight,calcfc,maxcyc=200) freq=numerical IOP(2/16=3) nosymm",
               "# pm3 opt=(verytight,gdiis,small) freq IOP(2/16=3)",
               "# pm3 opt=(verytight,nolinear,calcfc,small) freq IOP(2/16=3)",
               "# pm3 opt=(verytight,gdiis,maxcyc=200) freq=numerical IOP(2/16=3)",
               "# pm3 opt=tight freq IOP(2/16=3)",
               "# pm3 opt=tight freq=numerical IOP(2/16=3)",
               "# pm3 opt=(tight,nolinear,calcfc,small,maxcyc=200) freq IOP(2/16=3)",
               "# pm3 opt freq IOP(2/16=3)",
               "# pm3 opt=(verytight,gdiis) freq=numerical IOP(2/16=3) IOP(4/21=200)",
               "# pm3 opt=(calcfc,verytight,newton,notrustupdate,small,maxcyc=100,maxstep=100) freq=(numerical,step=10) IOP(2/16=3) nosymm",
               "# pm3 opt=(tight,gdiis,small,maxcyc=200,maxstep=100) freq=numerical IOP(2/16=3) nosymm",
               "# pm3 opt=(tight,gdiis,small,maxcyc=200,maxstep=100) freq=numerical IOP(2/16=3) nosymm",
               "# pm3 opt=(verytight,gdiis,calcall,small,maxcyc=200) IOP(2/16=3) IOP(4/21=2) nosymm",
               "# pm3 opt=(verytight,gdiis,calcall,small) IOP(2/16=3) nosymm",
               "# pm3 opt=(calcall,small,maxcyc=100) IOP(2/16=3)",
               ]
    
    @property
    def scriptAttempts(self):
        "The number of attempts with different script keywords"
        return len(self.keywords)
    
    @property
    def maxAttempts(self):
        "The total number of attempts to try"
        return 2 * len(self.keywords)
    
    def inputFileKeywords(self, attempt):
        """
        Return the top keywords for attempt number `attempt`.
    
        NB. `attempt`s begin at 1, not 0.
        """
        assert attempt <= self.maxAttempts
        if attempt > self.scriptAttempts:
            attempt -= self.scriptAttempts
        return self.keywords[attempt-1]    

# class GaussianTS(QMReaction, Gaussian):
#     #*****change this stuff for TS
#     "Keywords for the multiplicity"
#     multiplicityKeywords = {}
#     multiplicityKeywords[1] = ''
#     multiplicityKeywords[2] = 'uhf doublet'
#     multiplicityKeywords[3] = 'uhf triplet'
#     multiplicityKeywords[4] = 'uhf quartet'
#     multiplicityKeywords[5] = 'uhf quintet'
#     multiplicityKeywords[6] = 'uhf sextet'
#     multiplicityKeywords[7] = 'uhf septet'
#     multiplicityKeywords[8] = 'uhf octet'
#     multiplicityKeywords[9] = 'uhf nonet'
# 
#     "Keywords that will be added at the top of the qm input file"
#     keywordsTop = {}
#     keywordsTop[1] = "ts"
#     keywordsTop[2] = "ts recalc=5"
#     keywordsTop[3] = "ts ddmin=0.0001"
#     keywordsTop[4] = "ts recalc=5 ddmin=0.0001"
# 
#     "Keywords that will be added at the bottom of the qm input file"
#     keywordsBottom = {}
#     keywordsBottom[1] = "oldgeo force vectors esp"
#     keywordsBottom[2] = "oldgeo force vectors esp"
#     keywordsBottom[3] = "oldgeo force vectors esp"
#     keywordsBottom[4] = "oldgeo force vectors esp"
# 
#     scriptAttempts = len(keywordsTop)
# 
#     failureKeys = ['GRADIENT IS TOO LARGE', 
#                 'EXCESS NUMBER OF OPTIMIZATION CYCLES', 
#                 'NOT ENOUGH TIME FOR ANOTHER CYCLE',
#                 '6 IMAGINARY FREQUENCIES',
#                 '5 IMAGINARY FREQUENCIES',
#                 '4 IMAGINARY FREQUENCIES',
#                 '3 IMAGINARY FREQUENCIES',
#                 '2 IMAGINARY FREQUENCIES'
#                 ]
# 
#     def __init__(self, reaction):
#         self.reaction = reaction
#         self.reactants = reaction.reactants
#         self.products = reaction.products
#         self.family = reaction.family
#         self.rdmol = None
# 
#     def generateTransitionState(self):
#         """
#         make TS geometry
#         """
#         if not os.path.exists(self.reaction.family.name):
#             logging.info("Creating directory %s for mol files."%os.path.abspath(self.reaction.family.name))
#             os.makedirs(self.reaction.family.name)
#         inputFilePath = os.path.join(self.reaction.family.name, self.reactants[0].toAugmentedInChIKey())
#         if os.path.exists(inputFilePath):
#             inputFilePath = os.path.join(self.reaction.family.name, self.products[0].toAugmentedInChIKey())
#             if os.path.exists(inputFilePath):
#                 inputFilePath = os.path.join(self.reaction.family.name, self.reactants[0].toAugmentedInChIKey() + self.products[0].toAugmentedInChIKey())
#         with open(inputFilePath, 'w') as mopacFile:
#             for reactant in self.reactants:
#                 mopacFile.write(reactant.toSMILES())
#                 mopacFile.write('\n')
#                 mopacFile.write(reactant.toAdjacencyList())
#                 mopacFile.write('\n')
#             for product in self.products:
#                 mopacFile.write(product.toSMILES())
#                 mopacFile.write('\n')
#                 mopacFile.write(product.toAdjacencyList())
#                 mopacFile.write('\n')
# 
# 
# class GaussianTSPM3(GaussianTS):
#     def inputFileKeys(self, attempt, multiplicity):
#         """
#         Inherits the writeInputFile methods from mopac.py
#         """
#         multiplicity_keys = self.multiplicityKeywords[multiplicity]
# 
#         top_keys = "pm3 {0} {1}".format(
#                 multiplicity_keys,
#                 self.keywordsTop[attempt],
#                 )
#         bottom_keys = "{0} pm3 {1}".format(
#                 self.keywordsBottom[attempt],
#                 multiplicity_keys,
#                 )
#         polar_keys = "oldgeo {0} nosym precise pm3 {1}".format(
#                 'polar' if multiplicity == 1 else 'static',
#                 multiplicity_keys,
#                 )
# 
#         return top_keys, bottom_keys, polar_keys