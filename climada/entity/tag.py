"""
Define Tag class.
"""

class Tag(object):
    """Definition of one Exposures, Discounts, ImpactFuncs or Measures tag.

    Attributes
    ----------
        file_name (str): name of the source file
        description (str): description of the data
    """

    def __init__(self, file_name=None, description=None):
        """Initialize values.

        Parameters
        ----------
            file_name (str, optional): file name to read
            description (str, optional): description of the data
        """
        self.file_name = file_name
        self.description = description
        #self._next = 'NA'
        #self._prev = 'NA'