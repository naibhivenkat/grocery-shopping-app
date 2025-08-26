package com.example.groceryshoppingapp.models

import android.os.Parcelable
import kotlinx.parcelize.Parcelize

@Parcelize
data class CartItem(
    val item: Item,
    var quantity: Int
) : Parcelable

